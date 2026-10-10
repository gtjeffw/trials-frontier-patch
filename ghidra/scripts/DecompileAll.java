// Decompile every function into <out dir>/<namespace>/<address>_<name>.c, each headed by its callers, plus
// <out dir>/index.tsv (address, name, file). For grep-able browsing of the whole program; the output is derived from
// the game and belongs in the private workspace, never in this repository.
// Usage: tools/ghidra-headless.sh <project dir> TrialsFrontier -process TrialsFrontier -noanalysis -readOnly
//          -scriptPath ghidra/scripts -postScript DecompileAll.java <out dir>
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;

public class DecompileAll extends GhidraScript {
    @Override
    protected void run() throws Exception {
        File out = new File(getScriptArgs()[0]);
        out.mkdirs();
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        int n = 0, failed = 0;
        try (PrintWriter index = new PrintWriter(new File(out, "index.tsv"), StandardCharsets.UTF_8)) {
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                if (monitor.isCancelled()) break;
                if (f.isThunk() || f.isExternal()) continue;
                String full = f.getName(true);
                String ns = full.contains("::") ? full.substring(0, full.indexOf("::")) : "_global";
                ns = ns.replaceAll("[^A-Za-z0-9_.-]", "_");
                if (ns.length() > 60) ns = ns.substring(0, 60);
                String base = f.getName().replaceAll("[^A-Za-z0-9_.-]", "_");
                if (base.length() > 80) base = base.substring(0, 80);
                File dir = new File(out, ns);
                dir.mkdirs();
                String file = f.getEntryPoint() + "_" + base + ".c";
                StringBuilder sb = new StringBuilder();
                sb.append("// ").append(full).append(" @ ").append(f.getEntryPoint()).append("\n");
                for (Reference r : getReferencesTo(f.getEntryPoint())) {
                    Function c = getFunctionContaining(r.getFromAddress());
                    sb.append("// caller ").append(r.getFromAddress()).append(" ").append(r.getReferenceType())
                      .append(" ").append(c == null ? "?" : c.getName(true)).append("\n");
                }
                DecompileResults res = ifc.decompileFunction(f, 60, monitor);
                if (res != null && res.decompileCompleted()) {
                    sb.append(res.getDecompiledFunction().getC());
                } else {
                    sb.append("// decompilation failed\n");
                    failed++;
                }
                try (PrintWriter w = new PrintWriter(new File(dir, file), StandardCharsets.UTF_8)) {
                    w.print(sb);
                }
                index.println(f.getEntryPoint() + "\t" + full + "\t" + ns + "/" + file);
                if (++n % 2000 == 0) println("decompiled " + n);
            }
        }
        println("done: " + n + " functions (" + failed + " failed) in " + out);
    }
}
