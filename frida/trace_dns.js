// Log every hostname the process resolves (getaddrinfo), with the first game frame that asked for it.
// Usage: frida -p <pid> -q -t 3600 -l frida/trace_dns.js   (stay attached)
const ts = () => new Date().toISOString().slice(11, 19);
const seen = new Map();
Interceptor.attach(Process.getModuleByName("libsystem_info.dylib").getExportByName("getaddrinfo"), {
  onEnter(a) {
    const host = a[0].isNull() ? "(null)" : a[0].readUtf8String();
    const fr = Thread.backtrace(this.context, Backtracer.FUZZY).map(DebugSymbol.fromAddress)
      .find(s => s.moduleName === "TrialsFrontier");
    const key = host + " <- " + (fr ? fr.name : "?");
    const n = (seen.get(key) || 0) + 1;
    seen.set(key, n);
    if (n === 1) console.log(`${ts()} getaddrinfo ${key}`);
  }
});
console.log("dns tracer attached");
