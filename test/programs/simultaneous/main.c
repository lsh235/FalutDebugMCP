#define _DEFAULT_SOURCE
#include <pthread.h>
#include <signal.h>
#include <unistd.h>
static void *boom(void *p){(void)p;usleep(1000);volatile int *x=(int*)0;*x=1;return 0;}
int main(void){pthread_t a,b;pthread_create(&a,0,boom,0);pthread_create(&b,0,boom,0);pthread_join(a,0);pthread_join(b,0);return 0;}
