# modification 1
<file>src/libcrun/container.c</file>
<original>  execvp (def->process->args[0], def->process->args);
  if (errno == ENOENT)
    return crun_make_error (err, errno, "executable file not found in $PATH");

  return crun_make_error (err, errno, "exec the container process");</original>
<patched>  execv (def->process->args[0], def->process->args);
  if (errno == ENOENT)
    return crun_make_error (err, errno, "executable file not found");

  return crun_make_error (err, errno, "exec the container process");</patched>

# modification 2
<file>src/libcrun/container.c</file>
<original>      execvp (process->args[0], process->args);
      if (errno == ENOENT)
        libcrun_fail_with_error (