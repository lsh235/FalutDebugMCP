#include <stdlib.h>
static volatile int sink;
__attribute__((noinline)) static void left_leaf(void){sink+=1;}
__attribute__((noinline)) static void right_leaf(void){sink+=2;}
__attribute__((noinline)) static void branch(int n){if(n&1)left_leaf();else right_leaf();}
int main(int argc,char **argv){branch(argc>1?atoi(argv[1]):1);return 0;}
