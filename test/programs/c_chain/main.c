#include "chain.h"
#include <stdlib.h>
#include <unistd.h>
static void terminal_fault(void){ volatile int *p=(int*)sysconf(_SC_PAGESIZE); (void)p; __builtin_trap(); }
int main(int argc,char **argv){ int depth=argc>1?atoi(argv[1]):16; if(depth<1)depth=1;if(depth>64)depth=64; fd_chain_a1(depth); if(argc>2 && argv[2][0]=='f') terminal_fault(); return 0; }
