#include <signal.h>
#include <stdlib.h>
static volatile unsigned long sink;
__attribute__((noinline)) static void recurse(unsigned long n){char pad[4096];pad[0]=(char)n;sink+=pad[0];recurse(n+1);}
int main(void){recurse(1);return 0;}
