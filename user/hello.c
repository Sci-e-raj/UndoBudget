#include "kernel/types.h"
#include "user/user.h"

int
main(void)
{
  int result = hello(1, 2, 3, 4);
  printf("hello(1,2,3,4) = %d\n", result);
  if (result != 10 || hello(-1, -2, -3, -4) != -10 ||
      hello(0, 0, 0, 0) != 0 ||
      hello(2147483647, 2147483647, -2147483647, -2147483647) != 0 ||
      hello(2147483647, 1, 0, 0) != -1 ||
      hello(-2147483647 - 1, -1, 0, 0) != -1) {
    fprintf(2, "hello: FAIL\n");
    exit(1);
  }
  printf("hello: PASS\n");
  exit(0);
}
