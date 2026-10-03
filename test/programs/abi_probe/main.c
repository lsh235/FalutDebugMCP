#include "faultdebug/format.h"

#include <stddef.h>
#include <stdio.h>

int main(void) {
  if (sizeof(struct fd_shared_header) != 80 ||
      sizeof(struct fd_rpc_sidecar_header) != 64 ||
      sizeof(struct fd_rpc_event) != 96 ||
      offsetof(struct fd_rpc_event, rpc_id) != 8 ||
      offsetof(struct fd_rpc_event, direction) != 72 ||
      offsetof(struct fd_rpc_event, status) != 76 ||
      offsetof(struct fd_rpc_event, flags) != 80 ||
      offsetof(struct fd_rpc_event, reserved) != 88) {
    fprintf(stderr, "faultdebug ABI v1/v0.9 layout mismatch\n");
    return 1;
  }
  puts("faultdebug-abi-probe: PASS");
  return 0;
}
