param([int]$TargetPid)
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class KeepAwakeNative {
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern uint SetThreadExecutionState(uint flags);
}
"@
try {
  while (Get-Process -Id $TargetPid -ErrorAction SilentlyContinue) {
    $r=[KeepAwakeNative]::SetThreadExecutionState([uint32]2147483649)
    if ($r -eq 0) { throw 'SetThreadExecutionState failed.' }
    Start-Sleep -Seconds 30
  }
} finally {
  [KeepAwakeNative]::SetThreadExecutionState([uint32]2147483648) | Out-Null
}
