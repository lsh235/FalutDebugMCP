#define _GNU_SOURCE
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <stdio.h>
#include <dirent.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <sys/types.h>
static _Thread_local volatile uint64_t sink;
static volatile sig_atomic_t stop;
static void *churn(void *p){uint64_t n=(uintptr_t)p;for(int i=0;i<10000&&!stop;i++)sink+=n+i;return 0;}

static long current_rss_kb(void){
  FILE *f=fopen("/proc/self/statm","r");if(!f)return -1;
  long total=0,resident=0;int ok=fscanf(f,"%ld %ld",&total,&resident);fclose(f);
  long page=sysconf(_SC_PAGESIZE);if(ok!=2||page<=0)return -1;
  return resident*page/1024;
}

static long open_fd_count(void){
  DIR *dir=opendir("/proc/self/fd");if(!dir)return -1;
  int own_fd=dirfd(dir);long count=0;struct dirent *entry;
  while((entry=readdir(dir))!=0){
    char *end=0;errno=0;long fd=strtol(entry->d_name,&end,10);
    if(errno==0&&end&&*end=='\0'&&fd>=0&&fd!=own_fd)count++;
  }
  closedir(dir);return count;
}

static long long recorder_mapping_bytes(void){
  const char *value=getenv("FAULTDEBUG_SHM_FD");if(!value||!*value)return -1;
  char *end=0;errno=0;long fd=strtol(value,&end,10);
  if(errno!=0||!end||*end!='\0'||fd<0)return -1;
  struct stat st;if(fstat((int)fd,&st)!=0)return -1;
  return (long long)st.st_size;
}

static void report_sample(long elapsed){
  struct rusage usage;long peak=-1;
  if(getrusage(RUSAGE_SELF,&usage)==0)peak=usage.ru_maxrss;
  fprintf(stderr,"soak sample elapsed_s=%ld rss_current_kb=%ld rss_peak_kb=%ld fd_count=%ld recorder_mapping_bytes=%lld\n",
          elapsed,current_rss_kb(),peak,open_fd_count(),recorder_mapping_bytes());
  fflush(stderr);
}

static uint64_t elapsed_ns(struct timespec start,struct timespec end){
  int64_t seconds=(int64_t)end.tv_sec-(int64_t)start.tv_sec;
  int64_t nanoseconds=(int64_t)end.tv_nsec-(int64_t)start.tv_nsec;
  return (uint64_t)(seconds*INT64_C(1000000000)+nanoseconds);
}

int main(int argc,char **argv){
  int seconds=argc>1?atoi(argv[1]):1800;struct timespec s,n;
  clock_gettime(CLOCK_MONOTONIC,&s);long last=0;
  for(;;){
    clock_gettime(CLOCK_MONOTONIC,&n);uint64_t elapsed=elapsed_ns(s,n);
    if(elapsed>=(uint64_t)seconds*UINT64_C(1000000000)||stop)break;
    pthread_t t[8];for(int i=0;i<8;i++)pthread_create(&t[i],0,churn,(void*)(uintptr_t)i);
    for(int i=0;i<8;i++)pthread_join(t[i],0);
    long elapsed_seconds=(long)(elapsed/UINT64_C(1000000000));
    if(elapsed_seconds>=last+60){report_sample(elapsed_seconds);last=elapsed_seconds;}
    usleep(10000);
  }
  clock_gettime(CLOCK_MONOTONIC,&n);uint64_t elapsed=elapsed_ns(s,n);
  long elapsed_seconds=(long)(elapsed/UINT64_C(1000000000));
  if(elapsed_seconds>last)report_sample(elapsed_seconds);
  fprintf(stderr,"soak end elapsed_ns=%llu\n",(unsigned long long)elapsed);fflush(stderr);
  if(!stop){volatile int *p=(int*)0;*p=1;}
  return 0;
}
