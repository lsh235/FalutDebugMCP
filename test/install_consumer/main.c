#include "faultdebug/rpc.h"

#include <stdint.h>

int main(void) {
  /* No launcher mapping is intentional: the installed ABI must remain a
   * safe no-op for an ordinary consumer until it opts into a mapping. */
  return fd_rpc_begin_attempt(UINT64_C(1), UINT64_C(2), UINT64_C(3),
                              UINT64_C(4), FD_RPC_DIRECTION_OUTBOUND, 1, 10) < 0;
}
