#include "kernel/types.h"
#include "kernel/fcntl.h"
#include "kernel/group.h"
#include "user/user.h"

// Measurement workload. Run each scenario on a fresh scratch filesystem.
// Budgets include exec=4 and 4 units per fixture before measured unlinks.
// Shell: fail=2/76/0, block=3/32/12, shared=4/40/0,
// race=5/84/0, independent=6/36/0 and 7/44/0.

static char *scenario;

static void
check(int ok, char *why)
{
  if (!ok) {
    fprintf(2, "budgetexperiment: FAIL %s: %s\n", scenario, why);
    exit(1);
  }
}

static void
word(char **cursor, char *value)
{
  while (*value)
    *(*cursor)++ = *value++;
}

static void
number(char **cursor, uint64 value)
{
  char reversed[24];
  int count = 0;
  do {
    reversed[count++] = '0' + value % 10;
    value /= 10;
  } while (value);
  while (count)
    *(*cursor)++ = reversed[--count];
}

struct observation {
  char *event;
  uint tick;
  int attempts;
  int completed;
  int result;
  struct budget_snapshot state;
};

static void
sample(struct observation *o, char *event, int gid, int attempts, int completed,
       int result)
{
  o->event = event;
  o->tick = (uint)uptime();
  o->attempts = attempts;
  o->completed = completed;
  o->result = result;
  check(budgetstat(gid, &o->state) == 0, "budget snapshot");
}

static void
emit_record(struct observation *o, int gid)
{
  char line[512], *p = line;
  word(&p, "UBEXP case=");
  word(&p, scenario);
  word(&p, " event=");
  word(&p, o->event);
  word(&p, " tick=");
  number(&p, o->tick);
  word(&p, " gid=");
  number(&p, gid);
  word(&p, " pid=");
  number(&p, getpid());
  word(&p, " attempts=");
  number(&p, o->attempts);
  word(&p, " completed=");
  number(&p, o->completed);
  word(&p, " result=");
  number(&p, o->result); // 0=refused, 1=success, 2=sample
  word(&p, " remaining=");
  number(&p, o->state.remaining);
  word(&p, " max=");
  number(&p, o->state.max);
  word(&p, " allowed=");
  number(&p, o->state.n_allowed);
  word(&p, " blocked=");
  number(&p, o->state.n_blocked);
  word(&p, " refused=");
  number(&p, o->state.n_refused);
  *p++ = '\n';
  check(write(1, line, p - line) == p - line, "write measurement");
}

static void
emit(char *event, int gid, int attempts, int completed, int result)
{
  struct observation o;
  sample(&o, event, gid, attempts, completed, result);
  emit_record(&o, gid);
}

static int
exists(char *path)
{
  int fd = open(path, O_RDONLY);
  if (fd < 0)
    return 0;
  close(fd);
  return 1;
}

static void
fixture(char *path)
{
  check(!exists(path), "fresh filesystem required");
  int fd = open(path, O_CREATE | O_RDWR);
  check(fd >= 0 && close(fd) == 0, "create fixture");
}

static void
setup(int gid, int maximum, int refill, int mode)
{
  struct budget_snapshot state;
  check(setgroup(gid) == 0 && setgroup(0) == -1,
        "shell selected immutable workload group");
  check(budgetstat(gid, &state) == 0 && state.configured &&
          state.max == maximum && state.remaining == maximum - 4 &&
          state.refill_per_100_ticks == refill && state.mode == mode &&
          state.n_allowed == 1 && state.n_blocked == 0 && state.n_refused == 0,
        "only user exec charged before workload");
}

static void
fail_plateau(void)
{
  char *paths[] = {"ef0", "ef1", "ef2", "ef3", "ef4", "ef5"};
  setup(2, 76, 0, BUDGET_FAIL);
  for (int i = 0; i < 6; i++)
    fixture(paths[i]);
  emit("start", 2, 0, 0, 2);
  for (int i = 0; i < 6; i++) {
    int rc = unlink(paths[i]);
    check((i < 4 ? rc == 0 && !exists(paths[i]) : rc == -1 && exists(paths[i])),
          "FAIL plateau result");
    emit("attempt", 2, i + 1, i < 4 ? i + 1 : 4, rc == 0);
    check(pause(10) == 0, "pace attempts");
  }
  check(pause(100) == 0, "observe plateau after 100 ticks");
  emit("end", 2, 6, 4, 2);
}

static void
block_staircase(void)
{
  char *paths[] = {"eb0", "eb1", "eb2", "eb3"};
  setup(3, 32, 12, BUDGET_BLOCK);
  for (int i = 0; i < 4; i++)
    fixture(paths[i]);
  int pid = fork();
  check(pid >= 0, "fork BLOCK worker");
  if (pid == 0) {
    for (int i = 0; i < 4; i++) {
      if (unlink(paths[i]) != 0)
        exit(1);
    }
    exit(0);
  }
  emit("start", 3, 0, 0, 2);
  uint start = (uint)uptime();
  for (;;) {
    // Observe actual deletion effects, not just charges admitted by the kernel.
    int completed = 0;
    for (int i = 0; i < 4; i++)
      completed += !exists(paths[i]);
    emit("sample", 3, completed, completed, 2);
    if (completed == 4)
      break;
    if ((uint)uptime() - start > 450) {
      kill(pid);
      check(0, "BLOCK worker exceeded 450 ticks");
    }
    check(pause(10) == 0, "poll interval");
  }
  int status = -1;
  check(wait(&status) == pid && status == 0, "BLOCK worker completed");
  for (int i = 0; i < 4; i++)
    check(!exists(paths[i]), "BLOCK target removed");
  struct budget_snapshot state;
  check(budgetstat(3, &state) == 0, "final BLOCK snapshot");
  check(state.n_blocked >= 3 && state.n_refused == 0,
        "BLOCK waited without refusal");
  emit("end", 3, 4, 4, 2);
}

static void
shared_fork(void)
{
  char *paths[] = {"es0", "es1", "es2"};
  setup(4, 40, 0, BUDGET_FAIL);
  for (int i = 0; i < 3; i++)
    fixture(paths[i]);
  emit("start", 4, 0, 0, 2);
  int pid = fork();
  check(pid >= 0, "fork shared spender");
  if (pid == 0) {
    check(setgroup(4) == 0 && setgroup(0) == -1, "child inherited gid");
    exit(unlink(paths[0]) == 0 ? 0 : 1);
  }
  int status = -1;
  check(wait(&status) == pid && status == 0 && !exists(paths[0]),
        "child spent shared budget");
  emit("child", 4, 1, 1, 1);
  check(unlink(paths[1]) == 0 && !exists(paths[1]), "parent spent remainder");
  emit("parent", 4, 2, 2, 1);
  check(unlink(paths[2]) == -1 && exists(paths[2]),
        "shared budget refused third unlink");
  emit("end", 4, 3, 2, 0);
}

static void
concurrent(void)
{
  char *paths[] = {"ec0", "ec1", "ec2", "ec3", "ec4", "ec5", "ec6", "ec7"};
  setup(5, 84, 0, BUDGET_FAIL);
  for (int i = 0; i < 8; i++)
    fixture(paths[i]);
  int ready[2], release[2];
  check(pipe(ready) == 0 && pipe(release) == 0, "barrier pipes");
  for (int i = 0; i < 8; i++) {
    int pid = fork();
    check(pid >= 0, "fork contender");
    if (pid == 0) {
      close(ready[0]);
      close(release[1]);
      if (write(ready[1], "r", 1) != 1)
        exit(2);
      char token;
      if (read(release[0], &token, 1) != 1)
        exit(2);
      int rc = unlink(paths[i]);
      exit(rc == 0 ? 0 : rc == -1 ? 1 : 2);
    }
  }
  close(ready[1]);
  close(release[0]);
  for (int i = 0; i < 8; i++) {
    char token;
    check(read(ready[0], &token, 1) == 1 && token == 'r',
          "all contenders ready");
  }
  close(ready[0]);
  emit("start", 5, 0, 0, 2);
  check(write(release[1], "xxxxxxxx", 8) == 8, "release contenders");
  close(release[1]);
  int completed = 0, refused = 0;
  for (int i = 0; i < 8; i++) {
    int status = -1;
    check(wait(&status) > 0 && (status == 0 || status == 1),
          "contender returned unlink result");
    completed += status == 0;
    refused += status == 1;
    emit("sample", 5, completed + refused, completed, 2);
  }
  int removed = 0;
  for (int i = 0; i < 8; i++)
    removed += !exists(paths[i]);
  struct budget_snapshot state;
  check(budgetstat(5, &state) == 0 && completed == 4 && refused == 4 &&
          removed == 4 && state.remaining == 0 && state.n_allowed == 13 &&
          state.n_refused == 4,
        "atomic shared balance and surviving targets");
  emit("end", 5, 8, 4, 2);
}

static void
independent(int gid)
{
  char *paths6[] = {"ei60", "ei61", "ei62"};
  char *paths7[] = {"ei70", "ei71", "ei72"};
  char **paths = gid == 6 ? paths6 : paths7;
  char *own = gid == 6 ? "ei6ready" : "ei7ready";
  char *other = gid == 6 ? "ei7ready" : "ei6ready";
  int expected = gid == 6 ? 1 : 2;
  setup(gid, gid == 6 ? 36 : 44, 0, BUDGET_FAIL);
  for (int i = 0; i < 3; i++)
    fixture(paths[i]);
  fixture(own);
  emit("ready", gid, 0, 0, 2);
  int seen = 0;
  for (int i = 0; i < 200; i++) {
    if (exists(other)) {
      seen = 1;
      break;
    }
    check(pause(1) == 0, "wait for peer group");
  }
  check(seen, "peer reached barrier");
  // Keep original tick/snapshot values, then serialize the console output:
  // consolewrite splits writes into 32-byte chunks that can interleave.
  struct observation points[5];
  sample(&points[0], "start", gid, 0, 0, 2);
  for (int i = 0; i < 3; i++) {
    int rc = unlink(paths[i]);
    check((i < expected ? rc == 0 && !exists(paths[i])
                        : rc == -1 && exists(paths[i])),
          "independent balance and target state");
    sample(&points[i + 1], "attempt", gid, i + 1,
           i < expected ? i + 1 : expected, rc == 0);
    check(pause(10) == 0, "pace group attempts");
  }
  sample(&points[4], "end", gid, 3, expected, 2);
  if (gid == 7) {
    seen = 0;
    for (int i = 0; i < 200; i++) {
      if (exists("ei6done")) {
        seen = 1;
        break;
      }
      check(pause(1) == 0, "wait for group 6 report");
    }
    check(seen, "group 6 reported completion");
  }
  for (int i = 0; i < 5; i++)
    emit_record(&points[i], gid);
  if (gid == 6)
    fixture("ei6done");
}

int
main(int argc, char **argv)
{
  scenario = "argument";
  check(argc >= 2, "usage: budgetexperiment MODE [GID]");
  scenario = argv[1];
  if (argc == 2 && strcmp(scenario, "fail") == 0)
    fail_plateau();
  else if (argc == 2 && strcmp(scenario, "block") == 0)
    block_staircase();
  else if (argc == 2 && strcmp(scenario, "shared") == 0)
    shared_fork();
  else if (argc == 2 && strcmp(scenario, "race") == 0)
    concurrent();
  else if (argc == 3 && strcmp(scenario, "independent") == 0 &&
           (strcmp(argv[2], "6") == 0 || strcmp(argv[2], "7") == 0))
    independent(argv[2][0] - '0');
  else
    check(0, "unknown mode or group");
  exit(0);
}
