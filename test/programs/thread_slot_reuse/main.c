#include <pthread.h>
#include <stdlib.h>
static void *one(void *p){volatile int x=*(int*)p;(void)x;return 0;}
int main(int argc,char **argv){int n=argc>1?atoi(argv[1]):80;for(int i=0;i<n;i++){pthread_t t;pthread_create(&t,0,one,&i);pthread_join(t,0);}return 0;}
