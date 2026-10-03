#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <pthread.h>

namespace {

constexpr std::uint64_t kFunctionCallsPerIteration = 3;
pthread_barrier_t g_start_barrier;
std::uint64_t g_iterations_per_thread;

struct WorkerInput {
  std::uint64_t worker;
  std::uint64_t *result;
};

__attribute__((noinline)) std::uint64_t leaf(std::uint64_t value) {
  return (value ^ (value >> 7)) * UINT64_C(0x9e3779b185ebca87);
}

__attribute__((noinline)) std::uint64_t combine(std::uint64_t state,
                                                std::uint64_t iteration) {
  return state + leaf(state ^ (iteration + UINT64_C(0x517cc1b727220a95))) + iteration;
}

__attribute__((noinline)) void step(std::uint64_t *state,
                                    std::uint64_t iteration) {
  *state = combine(*state, iteration);
}

__attribute__((noinline)) void *run_worker(void *opaque) {
  const auto &input = *static_cast<WorkerInput *>(opaque);
  pthread_barrier_wait(&g_start_barrier);
  std::uint64_t state = UINT64_C(0x243f6a8885a308d3) ^ input.worker;
  for (std::uint64_t iteration = 0; iteration < g_iterations_per_thread; ++iteration) {
    step(&state, iteration);
  }
  *input.result = state;
  return nullptr;
}

}  // namespace

int main(int argc, char **argv) {
  const std::uint64_t thread_count = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 32;
  const std::uint64_t iterations_per_thread = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 500;
  if (thread_count == 0 || thread_count > 256 || iterations_per_thread == 0 ||
      iterations_per_thread > 1000000) return 2;
  g_iterations_per_thread = iterations_per_thread;
  std::uint64_t results[256] = {};
  pthread_t workers[256];
  WorkerInput inputs[256] = {};
  if (pthread_barrier_init(&g_start_barrier, nullptr, static_cast<unsigned int>(thread_count + 1)) != 0) return 3;
  for (std::uint64_t worker = 0; worker < thread_count; ++worker) {
    inputs[worker] = {worker, &results[worker]};
    if (pthread_create(&workers[worker], nullptr, run_worker, &inputs[worker]) != 0) return 4;
  }
  pthread_barrier_wait(&g_start_barrier);
  for (std::uint64_t worker = 0; worker < thread_count; ++worker) {
    if (pthread_join(workers[worker], nullptr) != 0) return 5;
  }
  pthread_barrier_destroy(&g_start_barrier);
  std::uint64_t checksum = 0;
  for (std::uint64_t worker = 0; worker < thread_count; ++worker) {
    checksum ^= results[worker];
  }
  const auto function_calls = thread_count * iterations_per_thread * kFunctionCallsPerIteration;
  std::printf("threads=%" PRIu64 " iterations_per_thread=%" PRIu64
              " function_calls=%" PRIu64 " checksum=%" PRIu64 "\n",
              thread_count, iterations_per_thread, function_calls, checksum);
  return checksum == 0 ? 1 : 0;
}
