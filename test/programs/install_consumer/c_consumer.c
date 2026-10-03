#include <signal.h>
#include <stddef.h>
#include <string.h>

static __attribute__((noinline)) int c_leaf(int value) {
    return value + 7;
}

static __attribute__((noinline)) int c_middle(int value) {
    return c_leaf(value * 2);
}

static __attribute__((noinline)) int c_fault(void) {
    volatile int *invalid = (volatile int *)0;
    *invalid = 7;
    return 0;
}

static __attribute__((noinline)) int c_entry(int fault) {
    int value = c_middle(5);
    return fault ? c_fault() : value;
}

int main(int argc, char **argv) {
    int fault = argc > 1 && strcmp(argv[1], "--fault") == 0;
    int value = c_entry(fault);
    return value == 17 ? 0 : 3;
}
