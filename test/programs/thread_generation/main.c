#define _XOPEN_SOURCE 700
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct work {
  pthread_barrier_t *barrier;
  unsigned int leaves;
  int crash;
};

__attribute__((noinline)) static void leaf(unsigned int value) {
  volatile unsigned int sink = value;
  (void)sink;
}

static void *one(void *argument) {
  const struct work *work = argument;
  if (work->barrier) {
    int result = pthread_barrier_wait(work->barrier);
    if (result != 0 && result != PTHREAD_BARRIER_SERIAL_THREAD) return (void *)(uintptr_t)1;
  }
  for (unsigned int i = 0; i < work->leaves; ++i) leaf(i);
  if (work->crash) __builtin_trap();
  return NULL;
}

/* The controller must leave every configured recording slot to its workers. */
__attribute__((no_instrument_function)) int main(int argc, char **argv) {
  unsigned int count = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 10) : 80;
  const char *mode = argc > 2 ? argv[2] : "normal";
  unsigned int width = argc > 3 ? (unsigned int)strtoul(argv[3], NULL, 10) : 1;
  if (!count || count > 10000 || !width || width > 64 || count % width) return 64;
  for (unsigned int start = 0; start < count; start += width) {
    pthread_t threads[64];
    struct work work[64];
    pthread_barrier_t barrier;
    if (width > 1 && pthread_barrier_init(&barrier, NULL, width) != 0) return 2;
    for (unsigned int i = 0; i < width; ++i) {
      work[i] = (struct work){width > 1 ? &barrier : NULL,
                            (!strcmp(mode, "wrap") || (!strcmp(mode, "retired-overflow") &&
                             start + i + 1 < count)) ? 12u : 0u,
                            !strcmp(mode, "fault") && start + i + 1 == count};
      if (pthread_create(&threads[i], NULL, one, &work[i]) != 0) return 3;
    }
    for (unsigned int i = 0; i < width; ++i) {
      void *result = NULL;
      if (pthread_join(threads[i], &result) != 0 || result != NULL) return 4;
    }
    if (width > 1 && pthread_barrier_destroy(&barrier) != 0) return 5;
  }
  printf("workers=%u width=%u\n", count, width);
  return 0;
}
