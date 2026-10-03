#include <stdlib.h>
static volatile int sink;
__attribute__((noinline)) void fd_recurse(int n){sink+=n;if(n>0)fd_recurse(n-1);}
int main(int argc,char **argv){int n=argc>1?atoi(argv[1]):8;if(n<1)n=1;if(n>128)n=128;fd_recurse(n);return 0;}
