// For each address: print the containing function's name/entry and every caller (code refs to the entry).
// Usage: ... -postScript FuncInfo.java <addr> [...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class FuncInfo extends GhidraScript {
    @Override
    protected void run() throws Exception {
        for (String arg : getScriptArgs()) {
            arg = arg.trim();
            if (arg.isEmpty()) continue;
            Function f = getFunctionContaining(toAddr(arg));
            if (f == null) { System.out.println("FUNC " + arg + " -> (none)"); continue; }
            System.out.println("FUNC " + arg + " -> " + f.getName(true) + " @ " + f.getEntryPoint());
            for (Reference r : getReferencesTo(f.getEntryPoint())) {
                if (r.getFromAddress().getOffset() >= 0x101000000L) continue;
                Function c = getFunctionContaining(r.getFromAddress());
                System.out.println("   caller " + r.getFromAddress() + " " + r.getReferenceType() + " in " + (c == null ? "?" : c.getName(true)));
            }
        }
    }
}
