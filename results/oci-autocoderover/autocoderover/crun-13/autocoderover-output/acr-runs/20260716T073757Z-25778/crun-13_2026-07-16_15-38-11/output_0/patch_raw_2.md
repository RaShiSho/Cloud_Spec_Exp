# modification 1
```
<file>src/libcrun/utils.c</file>
<original>  execvp (args[0], args);</original>
<patched>  execve (args[0], args, environ);</patched>
```

# modification 2
```
<file>src/libcrun/utils.c</file>
<original>      execvpe (path, args, envp);</original>
<patched>      execve (path, args, envp);</patched>
```