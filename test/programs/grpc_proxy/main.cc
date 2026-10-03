// Asynchronous gRPC fixture for FaultDebug.
//
// The same binary can run an upstream service, an asynchronous proxy, or a
// small synchronous client.  The proxy completes the downstream RPC before
// optionally causing a real SIGSEGV in its CompletionQueue thread.  This
// gives the recorder a useful cross-RPC call path without requiring a fault in
// gRPC's own implementation.

#include "echo.grpc.pb.h"
#include "trace.h"

#include <grpcpp/grpcpp.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

using faultdebug::test::Echo;
using faultdebug::test::EchoReply;
using faultdebug::test::EchoRequest;

struct Options {
  std::string mode;
  std::string listen = "127.0.0.1:50051";
  std::string upstream = "127.0.0.1:50052";
  std::string message = "faultdebug-grpc";
  bool fault_after_response = false;
  int max_calls = 0;
  int workers = 1;
  int deadline_ms = 0;
  int response_delay_ms = 0;
  int stream_count = 3;
  int retry = 0;
  bool stream = false;
  bool json_output = false;
  uint64_t rpc_id = 1;
};

void Usage(const char* argv0) {
  std::cout
      << "Usage: " << argv0 << " --mode MODE [options]\n"
      << "  MODE: upstream | proxy | client\n"
      << "Options:\n"
      << "  --listen ADDR              server listen address (default "
      << "127.0.0.1:50051)\n"
      << "  --upstream ADDR            proxy upstream address (default "
      << "127.0.0.1:50052)\n"
      << "  --message TEXT             client request message\n"
      << "  --fault-after-response     proxy faults after downstream Finish\n"
      << "  --max-calls N              gracefully stop after N completed calls\n"
      << "  --workers N                CompletionQueue worker threads (default 1)\n"
      << "  --deadline-ms N            outbound deadline; 0 disables it\n"
      << "  --response-delay-ms N      upstream application delay before Finish\n"
      << "  --stream                   client invokes the server-streaming RPC\n"
      << "  --stream-count N           bounded stream messages (default 3)\n"
      << "  --retry N                  proxy retries UNAVAILABLE attempts\n"
      << "  --json-output              emit a machine-readable client result\n"
      << "  --rpc-id N                 numeric RPC correlation ID (default 1)\n"
      << "  --help                     show this help\n";
}

bool Value(const std::string& arg, const char* name, std::string* out) {
  const std::string prefix = std::string(name) + "=";
  if (arg.rfind(prefix, 0) == 0) {
    *out = arg.substr(prefix.size());
    return true;
  }
  return false;
}

bool Parse(int argc, char** argv, Options* options) {
  for (int i = 1; i < argc; ++i) {
    const std::string arg(argv[i]);
    if (arg == "--help" || arg == "-h") {
      Usage(argv[0]);
      return false;
    }
    if (Value(arg, "--mode", &options->mode) ||
        Value(arg, "--listen", &options->listen) ||
        Value(arg, "--upstream", &options->upstream) ||
        Value(arg, "--message", &options->message)) {
      continue;
    }
    std::string value;
    if (Value(arg, "--max-calls", &value)) {
      options->max_calls = std::atoi(value.c_str());
      continue;
    }
    if (Value(arg, "--workers", &value)) {
      options->workers = std::atoi(value.c_str());
      continue;
    }
    if (Value(arg, "--deadline-ms", &value)) {
      options->deadline_ms = std::atoi(value.c_str());
      continue;
    }
    if (Value(arg, "--response-delay-ms", &value)) {
      options->response_delay_ms = std::atoi(value.c_str());
      continue;
    }
    if (Value(arg, "--stream-count", &value)) {
      options->stream_count = std::atoi(value.c_str());
      continue;
    }
    if (Value(arg, "--retry", &value)) {
      options->retry = std::atoi(value.c_str());
      continue;
    }
    if (Value(arg, "--rpc-id", &value)) {
      options->rpc_id = std::strtoull(value.c_str(), nullptr, 0);
      continue;
    }
    if (arg == "--fault-after-response") {
      options->fault_after_response = true;
      continue;
    }
    if (arg == "--stream") {
      options->stream = true;
      continue;
    }
    if (arg == "--json-output") {
      options->json_output = true;
      continue;
    }
    std::cerr << "unknown option: " << arg << "\n";
    Usage(argv[0]);
    return false;
  }
  if (options->mode != "upstream" && options->mode != "proxy" &&
      options->mode != "client") {
    std::cerr << "--mode must be upstream, proxy, or client\n";
    Usage(argv[0]);
    return false;
  }
  if (options->workers < 1 || options->deadline_ms < 0 ||
      options->response_delay_ms < 0 || options->stream_count < 1 ||
      options->retry < 0) {
    std::cerr << "--workers must be positive; counts and timing options must be non-negative\n";
    return false;
  }
  return true;
}

uint64_t NowNs() {
  return static_cast<uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
          std::chrono::steady_clock::now().time_since_epoch())
          .count());
}

class AsyncServer {
 public:
  AsyncServer(std::string address, int max_calls, int workers)
      : address_(std::move(address)), max_calls_(max_calls), workers_(workers) {}
  virtual ~AsyncServer() = default;

  AsyncServer(const AsyncServer&) = delete;
  AsyncServer& operator=(const AsyncServer&) = delete;

  virtual void Start() = 0;
  virtual void Wait() = 0;

 protected:
  bool CompleteCall() {
    if (max_calls_ <= 0) {
      return false;
    }
    return completed_calls_.fetch_add(1, std::memory_order_relaxed) + 1 >=
           max_calls_;
  }

  const std::string address_;
  const int max_calls_;
  const int workers_;
  std::atomic<int> completed_calls_{0};
};

class UpstreamServer final : public AsyncServer {
 private:
  class Completion {
   public:
    virtual ~Completion() = default;
    virtual void Proceed(bool ok) = 0;
  };

  class StreamData final : public Completion {
   public:
    StreamData(Echo::AsyncService* service, grpc::ServerCompletionQueue* cq,
               UpstreamServer* owner)
        : service_(service), cq_(cq), writer_(&ctx_), owner_(owner) {
      Proceed();
    }

    void Proceed(bool ok = true) override {
      if (!ok) {
        if (state_ != CREATE && rpc_id_ != 0) {
          fd_grpc_rpc_end_attempt(
              rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_STREAM,
              FD_RPC_DIRECTION_INBOUND, 1,
              static_cast<uint32_t>(grpc::StatusCode::CANCELLED), NowNs(),
              FD_RPC_EVENT_END | FD_RPC_EVENT_INCOMPLETE);
        }
        const bool stop = state_ != CREATE && owner_->CompleteCall();
        delete this;
        if (stop) owner_->ShutdownAsync();
        return;
      }
      if (state_ == CREATE) {
        service_->RequestStream(&ctx_, &request_, &writer_, cq_, cq_, this);
        state_ = WRITE;
        return;
      }
      if (state_ == WRITE && rpc_id_ == 0) {
        new StreamData(service_, cq_, owner_);
        rpc_id_ = request_.rpc_id() ? request_.rpc_id() : owner_->NextRpcId();
        trace_hi_ = request_.trace_id_hi();
        trace_lo_ = request_.trace_id_lo();
        remaining_ = owner_->stream_count_;
        fd_grpc_rpc_begin_attempt(
            rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_STREAM,
            FD_RPC_DIRECTION_INBOUND, 1, NowNs());
        SendNext();
        return;
      }
      if (state_ == WRITE) {
        if (remaining_ == 0) {
          state_ = FINISH;
          writer_.Finish(grpc::Status::OK, this);
          return;
        }
        SendNext();
        return;
      }
      fd_grpc_rpc_end_attempt(
          rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_STREAM,
          FD_RPC_DIRECTION_INBOUND, 1,
          static_cast<uint32_t>(grpc::StatusCode::OK), NowNs(),
          FD_RPC_EVENT_END);
      const bool stop = owner_->CompleteCall();
      delete this;
      if (stop) owner_->ShutdownAsync();
    }

   private:
    enum State { CREATE, WRITE, FINISH };

    void SendNext() {
      const int index = owner_->stream_count_ - remaining_ + 1;
      reply_.set_message("stream:" + std::to_string(index));
      --remaining_;
      writer_.Write(reply_, this);
    }

    Echo::AsyncService* service_;
    grpc::ServerCompletionQueue* cq_;
    grpc::ServerContext ctx_;
    EchoRequest request_;
    EchoReply reply_;
    grpc::ServerAsyncWriter<EchoReply> writer_;
    UpstreamServer* owner_;
    uint64_t rpc_id_ = 0;
    uint64_t trace_hi_ = 0;
    uint64_t trace_lo_ = 0;
    int remaining_ = 0;
    State state_ = CREATE;
  };

 public:
  UpstreamServer(std::string address, int max_calls, int workers,
                 int response_delay_ms, int stream_count)
      : AsyncServer(std::move(address), max_calls, workers),
        response_delay_ms_(response_delay_ms), stream_count_(stream_count) {}

  ~UpstreamServer() override {
    if (shutdown_thread_.joinable()) shutdown_thread_.join();
  }

  void Start() override {
    grpc::ServerBuilder builder;
    builder.AddListeningPort(address_, grpc::InsecureServerCredentials());
    builder.RegisterService(&service_);
    cq_ = builder.AddCompletionQueue();
    server_ = builder.BuildAndStart();
    if (!server_) {
      throw std::runtime_error("failed to start upstream gRPC server");
    }
    new CallData(&service_, cq_.get(), this);
    new StreamData(&service_, cq_.get(), this);
    std::cerr << "upstream listening on " << address_ << "\n";
  }

  void Wait() override {
    std::vector<std::thread> workers;
    for (int i = 0; i < workers_; ++i) {
        workers.emplace_back([this] {
        void* tag = nullptr;
        bool ok = false;
        while (cq_->Next(&tag, &ok)) {
          static_cast<Completion*>(tag)->Proceed(ok);
        }
      });
    }
    for (std::thread& worker : workers) worker.join();
  }

  void ShutdownAsync() {
    if (shutdown_started_.exchange(true, std::memory_order_acq_rel)) return;
    grpc::Server* server = server_.get();
    grpc::ServerCompletionQueue* cq = cq_.get();
    shutdown_thread_ = std::thread([server, cq] {
      server->Shutdown();
      cq->Shutdown();
    });
  }

 private:
  class CallData final : public Completion {
   public:
    CallData(Echo::AsyncService* service, grpc::ServerCompletionQueue* cq,
             UpstreamServer* owner)
        : service_(service), cq_(cq), responder_(&ctx_), owner_(owner) {
      Proceed();
    }

    void Proceed(bool ok = true) override {
      if (!ok) {
        if (state_ != CREATE && rpc_id_ != 0) {
          fd_grpc_rpc_end(rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_FORWARD,
                          FD_RPC_DIRECTION_INBOUND,
                          static_cast<uint32_t>(grpc::StatusCode::UNKNOWN),
                          NowNs(), FD_RPC_EVENT_END | FD_RPC_EVENT_INCOMPLETE);
        }
        const bool stop = state_ != CREATE && owner_->CompleteCall();
        delete this;
        if (stop) owner_->ShutdownAsync();
        return;
      }
      if (state_ == CREATE) {
        state_ = PROCESS;
        service_->RequestForward(&ctx_, &request_, &responder_, cq_, cq_, this);
        return;
      }
      if (state_ == PROCESS) {
        new CallData(service_, cq_, owner_);
        rpc_id_ = request_.rpc_id() ? request_.rpc_id() : owner_->NextRpcId();
        trace_hi_ = request_.trace_id_hi();
        trace_lo_ = request_.trace_id_lo();
        fd_grpc_rpc_begin(rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_FORWARD,
                          FD_RPC_DIRECTION_INBOUND, NowNs());
        if (owner_->response_delay_ms_ > 0) {
          std::this_thread::sleep_for(
              std::chrono::milliseconds(owner_->response_delay_ms_));
        }
        fd_grpc_trace_upstream_response();
        reply_.set_message("upstream:" + request_.message());
        state_ = FINISH;
        responder_.Finish(reply_, grpc::Status::OK, this);
        return;
      }
      fd_grpc_rpc_end(
          rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_FORWARD,
          FD_RPC_DIRECTION_INBOUND,
          static_cast<uint32_t>(ok ? grpc::StatusCode::OK
                                   : grpc::StatusCode::UNKNOWN),
          NowNs(), ok ? FD_RPC_EVENT_END : FD_RPC_EVENT_END | FD_RPC_EVENT_INCOMPLETE);
      const bool stop = owner_->CompleteCall();
      delete this;
      if (stop) {
        owner_->ShutdownAsync();
      }
    }

   private:
    enum State { CREATE, PROCESS, FINISH };
    Echo::AsyncService* service_;
    grpc::ServerCompletionQueue* cq_;
    grpc::ServerContext ctx_;
    EchoRequest request_;
    EchoReply reply_;
    grpc::ServerAsyncResponseWriter<EchoReply> responder_;
    UpstreamServer* owner_;
    uint64_t rpc_id_ = 0;
    uint64_t trace_hi_ = 0;
    uint64_t trace_lo_ = 0;
    State state_ = CREATE;
  };

  Echo::AsyncService service_;
  std::unique_ptr<grpc::ServerCompletionQueue> cq_;
  std::unique_ptr<grpc::Server> server_;
  int response_delay_ms_;
  int stream_count_;
  std::atomic<bool> shutdown_started_{false};
  std::thread shutdown_thread_;
  std::atomic<uint64_t> next_rpc_id_{1};

  uint64_t NextRpcId() {
    return next_rpc_id_.fetch_add(1, std::memory_order_relaxed);
  }
};

class ProxyServer final : public AsyncServer {
 public:
  ProxyServer(std::string address, std::string upstream, int max_calls,
              bool fault_after_response, int workers, int deadline_ms,
              int retry_limit)
      : AsyncServer(std::move(address), max_calls, workers),
        upstream_(std::move(upstream)),
        fault_after_response_(fault_after_response), deadline_ms_(deadline_ms),
        retry_limit_(retry_limit) {}

  ~ProxyServer() override {
    if (shutdown_thread_.joinable()) shutdown_thread_.join();
  }

  void Start() override {
    channel_ = grpc::CreateChannel(upstream_, grpc::InsecureChannelCredentials());
    stub_ = Echo::NewStub(channel_);
    grpc::ServerBuilder builder;
    builder.AddListeningPort(address_, grpc::InsecureServerCredentials());
    builder.RegisterService(&service_);
    cq_ = builder.AddCompletionQueue();
    server_ = builder.BuildAndStart();
    if (!server_) {
      throw std::runtime_error("failed to start proxy gRPC server");
    }
    new ProxyCall(&service_, cq_.get(), stub_.get(), this);
    std::cerr << "proxy listening on " << address_ << " -> " << upstream_
              << (fault_after_response_ ? " (fault enabled)" : "") << "\n";
  }

  void Wait() override {
    std::vector<std::thread> workers;
    for (int i = 0; i < workers_; ++i) {
      workers.emplace_back([this] {
        void* tag = nullptr;
        bool ok = false;
        while (cq_->Next(&tag, &ok)) {
          static_cast<Completion*>(tag)->Proceed(ok);
        }
      });
    }
    for (std::thread& worker : workers) worker.join();
  }

  void ShutdownAsync() {
    if (shutdown_started_.exchange(true, std::memory_order_acq_rel)) return;
    grpc::Server* server = server_.get();
    grpc::ServerCompletionQueue* cq = cq_.get();
    shutdown_thread_ = std::thread([server, cq] {
      server->Shutdown();
      cq->Shutdown();
    });
  }

 private:
  class Completion {
   public:
    virtual ~Completion() = default;
    virtual void Proceed(bool ok) = 0;
  };

  class ProxyCall;

  class ForwardCall final : public Completion {
   public:
    ForwardCall(ProxyCall* parent, Echo::Stub* stub,
                grpc::CompletionQueue* cq, const EchoRequest& request,
                int deadline_ms, uint64_t rpc_id, uint64_t trace_hi,
                uint64_t trace_lo, uint32_t attempt)
        : parent_(parent), cq_(cq), request_(request), rpc_id_(rpc_id),
          trace_hi_(trace_hi), trace_lo_(trace_lo), attempt_(attempt) {
      fd_grpc_rpc_begin_attempt(rpc_id_, trace_hi_, trace_lo_,
                                FD_GRPC_METHOD_FORWARD,
                                FD_RPC_DIRECTION_OUTBOUND, attempt_, NowNs());
      fd_grpc_trace_proxy_forwarded();
      if (deadline_ms > 0) {
        context_.set_deadline(std::chrono::system_clock::now() +
                              std::chrono::milliseconds(deadline_ms));
      }
      reader_ = stub->PrepareAsyncForward(&context_, request_, cq_);
      reader_->StartCall();
      reader_->Finish(&reply_, &status_, this);
    }

    void Proceed(bool ok) override {
      if (!ok) {
        fd_grpc_rpc_end_attempt(
            rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_FORWARD,
            FD_RPC_DIRECTION_OUTBOUND, attempt_,
            static_cast<uint32_t>(grpc::StatusCode::UNKNOWN), NowNs(),
            FD_RPC_EVENT_END | FD_RPC_EVENT_INCOMPLETE);
        parent_->Complete(
            EchoReply(),
            grpc::Status(grpc::StatusCode::UNAVAILABLE,
                         "upstream completion queue closed"));
        delete this;
        return;
      }
      fd_grpc_rpc_end_attempt(
          rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_FORWARD,
          FD_RPC_DIRECTION_OUTBOUND, attempt_,
          static_cast<uint32_t>(status_.error_code()), NowNs(),
          FD_RPC_EVENT_END);
      if (status_.error_code() == grpc::StatusCode::UNAVAILABLE &&
          attempt_ <= parent_->RetryLimit()) {
        parent_->Retry(attempt_ + 1);
        delete this;
        return;
      }
      parent_->Complete(reply_, status_);
      delete this;
    }

   private:
    ProxyCall* parent_;
    grpc::CompletionQueue* cq_;
    grpc::ClientContext context_;
    EchoRequest request_;
    EchoReply reply_;
    grpc::Status status_;
    std::unique_ptr<grpc::ClientAsyncResponseReader<EchoReply>> reader_;
    uint64_t rpc_id_;
    uint64_t trace_hi_;
    uint64_t trace_lo_;
    uint32_t attempt_;
  };

  class ProxyCall final : public Completion {
   public:
    ProxyCall(Echo::AsyncService* service, grpc::ServerCompletionQueue* cq,
              Echo::Stub* stub, ProxyServer* owner)
        : service_(service),
          cq_(cq),
          responder_(&ctx_),
          stub_(stub),
          owner_(owner) {
      Proceed(true);
    }

    void Proceed(bool ok) override {
      if (!ok) {
        if (state_ == FINISH) {
          fd_grpc_rpc_end_attempt(
              rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_FORWARD,
              FD_RPC_DIRECTION_INBOUND, 1,
              static_cast<uint32_t>(grpc::StatusCode::CANCELLED), NowNs(),
              FD_RPC_EVENT_END | FD_RPC_EVENT_INCOMPLETE);
          const bool stop = owner_->CompleteCall();
          delete this;
          if (stop) owner_->ShutdownAsync();
          return;
        }
        delete this;
        return;
      }
      if (state_ == CREATE) {
        state_ = WAIT_UPSTREAM;
        service_->RequestForward(&ctx_, &request_, &responder_, cq_, cq_, this);
        return;
      }
      if (state_ == WAIT_UPSTREAM) {
        new ProxyCall(service_, cq_, stub_, owner_);
        fd_grpc_trace_proxy_received();
        rpc_id_ = request_.rpc_id() ? request_.rpc_id() : owner_->NextRpcId();
        trace_hi_ = request_.trace_id_hi();
        trace_lo_ = request_.trace_id_lo();
        fd_grpc_rpc_begin_attempt(
            rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_FORWARD,
            FD_RPC_DIRECTION_INBOUND, 1, NowNs());
        new ForwardCall(this, stub_, cq_, request_, owner_->deadline_ms_,
                        rpc_id_, trace_hi_, trace_lo_, 1);
        state_ = FINISH;
        return;
      }
      fd_grpc_rpc_end_attempt(
          rpc_id_, trace_hi_, trace_lo_, FD_GRPC_METHOD_FORWARD,
          FD_RPC_DIRECTION_INBOUND, 1,
          static_cast<uint32_t>(ok ? status_.error_code()
                                   : grpc::StatusCode::UNKNOWN),
          NowNs(), ok ? FD_RPC_EVENT_END
                      : FD_RPC_EVENT_END | FD_RPC_EVENT_INCOMPLETE);
      const bool stop = owner_->CompleteCall();
      if (owner_->fault_after_response_) {
        // Completion of Finish is the point at which the downstream response
        // has been handed to gRPC.  Keep this a real memory fault so the
        // signal record contains the proxy completion path.
        fd_grpc_trace_proxy_fault_after_response();
      }
      delete this;
      if (stop) {
        owner_->ShutdownAsync();
      }
    }

    void Complete(const EchoReply& reply, const grpc::Status& status) {
      reply_ = reply;
      status_ = status;
      fd_grpc_trace_proxy_response();
      state_ = FINISH;
      responder_.Finish(reply_, status, this);
    }

    void Retry(uint32_t attempt) {
      new ForwardCall(this, stub_, cq_, request_, owner_->deadline_ms_,
                      rpc_id_, trace_hi_, trace_lo_, attempt);
    }

    int RetryLimit() const { return owner_->retry_limit_; }

   private:
    enum State { CREATE, WAIT_UPSTREAM, FINISH };
    Echo::AsyncService* service_;
    grpc::ServerCompletionQueue* cq_;
    grpc::ServerContext ctx_;
    EchoRequest request_;
    EchoReply reply_;
    grpc::Status status_;
    grpc::ServerAsyncResponseWriter<EchoReply> responder_;
    Echo::Stub* stub_;
    ProxyServer* owner_;
    uint64_t rpc_id_ = 0;
    uint64_t trace_hi_ = 0;
    uint64_t trace_lo_ = 0;
    State state_ = CREATE;
  };

  std::string upstream_;
  bool fault_after_response_;
  int deadline_ms_;
  int retry_limit_;
  Echo::AsyncService service_;
  std::unique_ptr<grpc::ServerCompletionQueue> cq_;
  std::unique_ptr<grpc::Server> server_;
  std::shared_ptr<grpc::Channel> channel_;
  std::unique_ptr<Echo::Stub> stub_;
  std::atomic<uint64_t> next_rpc_id_{1};
  std::atomic<bool> shutdown_started_{false};
  std::thread shutdown_thread_;

  uint64_t NextRpcId() {
    return next_rpc_id_.fetch_add(1, std::memory_order_relaxed);
  }

};

int RunClient(const Options& options) {
  auto channel = grpc::CreateChannel(options.listen,
                                     grpc::InsecureChannelCredentials());
  auto stub = Echo::NewStub(channel);
  grpc::ClientContext context;
  EchoRequest request;
  request.set_message(options.message);
  request.set_rpc_id(options.rpc_id);
  request.set_trace_id_hi(UINT64_C(0x4752504354524143));
  request.set_trace_id_lo(options.rpc_id);
  if (options.stream) {
    std::unique_ptr<grpc::ClientReader<EchoReply>> reader =
        stub->Stream(&context, request);
    EchoReply item;
    int messages = 0;
    while (reader->Read(&item)) {
      ++messages;
    }
    const grpc::Status status = reader->Finish();
    if (options.json_output) {
      std::cout << "{\"scenario\":\"stream\",\"status\":"
                << status.error_code() << ",\"messages\":" << messages
                << "}\n";
    } else if (status.ok()) {
      std::cout << "stream messages: " << messages << "\n";
    }
    if (!status.ok()) {
      if (!options.json_output) {
        std::cerr << "RPC stream failed: " << status.error_code() << " "
                  << status.error_message() << "\n";
      }
      return 2;
    }
    return 0;
  }
  EchoReply reply;
  const grpc::Status status = stub->Forward(&context, request, &reply);
  if (!status.ok()) {
    if (options.json_output) {
      std::cout << "{\"scenario\":\"unary\",\"status\":"
                << status.error_code() << "}\n";
    }
    std::cerr << "RPC failed: " << status.error_code() << " "
              << status.error_message() << "\n";
    return 2;
  }
  if (options.json_output) {
    std::cout << "{\"scenario\":\"unary\",\"status\":0}\n";
  } else {
    std::cout << reply.message() << "\n";
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  Options options;
  if (!Parse(argc, argv, &options)) {
    return argc > 1 && (std::strcmp(argv[1], "--help") == 0 ||
                        std::strcmp(argv[1], "-h") == 0)
               ? 0
               : 2;
  }
  try {
    if (options.mode == "client") {
      return RunClient(options);
    }
    std::unique_ptr<AsyncServer> server;
    if (options.mode == "upstream") {
      server = std::make_unique<UpstreamServer>(options.listen,
                                                options.max_calls, options.workers,
                                                options.response_delay_ms,
                                                options.stream_count);
    } else {
      server = std::make_unique<ProxyServer>(
          options.listen, options.upstream, options.max_calls,
          options.fault_after_response, options.workers, options.deadline_ms,
          options.retry);
    }
    server->Start();
    server->Wait();
  } catch (const std::exception& error) {
    std::cerr << "fatal: " << error.what() << "\n";
    return 1;
  }
  return 0;
}
