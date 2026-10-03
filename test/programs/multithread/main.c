#include <pthread.h>
#include <stdlib.h>
static _Thread_local volatile int sink;
static void *work(void *p){int n=*(int*)p;for(int i=0;i<n;i++)sink+=i;return 0;}
int main(int argc,char **argv){int n=argc>1?atoi(argv[1]):8;if(n<1)n=1;if(n>64)n=64;pthread_t t[64];int a[64];for(int i=0;i<n;i++){a[i]=i+1;pthread_create(&t[i],0,work,&a[i]);}for(int i=0;i<n;i++)pthread_join(t[i],0);return 0;}
