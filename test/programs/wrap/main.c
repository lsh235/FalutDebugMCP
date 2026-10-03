#include <stdlib.h>
static volatile int sink;
__attribute__((noinline)) static void event(void){sink++;}
int main(int argc,char **argv){int n=argc>1?atoi(argv[1]):4200;for(int i=0;i<n;i++)event();return 0;}
