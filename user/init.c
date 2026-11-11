// init: The initial user-level program

#include "kernel/types.h"
#include "kernel/stat.h"
#include "kernel/spinlock.h"
#include "kernel/sleeplock.h"
#include "kernel/fs.h"
#include "kernel/file.h"
#include "kernel/group.h"
#include "user/user.h"
#include "kernel/fcntl.h"

// Per-100-tick refills. The administrator must remain usable when charged;
// the default workload gets a smaller allowance and fails when exhausted.
#define ADMIN_MAX      10000
#define ADMIN_REFILL   1000
#define DEFAULT_MAX    1000
#define DEFAULT_REFILL 100

char *argv[] = {"sh", 0};

int
main(void)
{
  int pid, wpid;

  // Do this once, before console creation, output, or the shell's exec.
  // Exiting init on failure stops boot (kexit reports "init exiting").
  if (setbudget(0, ADMIN_MAX, ADMIN_REFILL, BUDGET_BLOCK) < 0)
    exit(1);
  if (setbudget(1, DEFAULT_MAX, DEFAULT_REFILL, BUDGET_FAIL) < 0)
    exit(1);

  if (open("console", O_RDWR) < 0) {
    mknod("console", CONSOLE, 0);
    open("console", O_RDWR);
  }
  dup(0); // stdout
  dup(0); // stderr

  for (;;) {
    printf("init: starting sh\n");
    pid = fork();
    if (pid < 0) {
      printf("init: fork failed\n");
      exit(1);
    }
    if (pid == 0) {
      exec("sh", argv);
      printf("init: exec sh failed\n");
      exit(1);
    }

    for (;;) {
      // this call to wait() returns if the shell exits,
      // or if a parentless process exits.
      wpid = wait((int *)0);
      if (wpid == pid) {
        // the shell exited; restart it.
        break;
      } else if (wpid < 0) {
        printf("init: wait returned an error\n");
        exit(1);
      } else {
        // it was a parentless process; do nothing.
      }
    }
  }
}
