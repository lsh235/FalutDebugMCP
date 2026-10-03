#include "faultdebug/rpc.h"

#include <stdint.h>

int main(void) {
  if (fd_rpc_begin(UINT64_C(0x7001), UINT64_C(0x1111), UINT64_C(0x2222),
                   UINT64_C(0x33), FD_RPC_DIRECTION_OUTBOUND, UINT64_C(10)) != 1)
    return 90;
  if (fd_rpc_end(UINT64_C(0x7001), UINT64_C(0x1111), UINT64_C(0x2222),
                 UINT64_C(0x33), FD_RPC_DIRECTION_OUTBOUND, 0, UINT64_C(20), 0) != 1)
    return 91;
  volatile int *invalid = (volatile int *)0;
  *invalid = 7;
  return 92;
}
