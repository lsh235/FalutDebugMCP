#include "faultdebug/rpc_scope.hpp"

int main() {
  faultdebug::rpc_span_scope span(
      0x9001, 0x1111, 0x2222, 0x33, FD_RPC_DIRECTION_OUTBOUND, 2, 10);
  span.finish(0);
  return 0;
}
