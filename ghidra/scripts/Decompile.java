// Decompile functions by address or symbol substring and print C to stdout.
// Usage: tools/ghidra-headless.sh ghidra TrialsFrontier -process TrialsFrontier -noanalysis -readOnly
//          -scriptPath ghidra/scripts -postScript Decompile.java <addr|name> [...]
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class Decompile extends GhidraScript {
    @Override
    protected void run() throws Exception {
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        for (String arg : getScriptArgs()) {
            arg = arg.trim();
            if (arg.isEmpty()) continue;
            Function f = null;
            if (arg.startsWith("0x")) {
                Address a = toAddr(arg);
                f = a == null ? null : getFunctionContaining(a);
            } else {
                for (Function c : currentProgram.getFunctionManager().getFunctions(true)) {
                    if (c.getName(true).contains(arg)) { f = c; break; }
                }
            }
            if (f == null) { println("// not found: " + arg); continue; }
            DecompileResults r = ifc.decompileFunction(f, 120, monitor);
            System.out.println("// ===== " + f.getName(true) + " @ " + f.getEntryPoint());
            System.out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// decompile failed: " + r.getErrorMessage());
        }
        ifc.dispose();
    }
}
