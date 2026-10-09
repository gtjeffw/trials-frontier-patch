// List functions in the main executable that have no references at all (no calls, no data/vtable refs),
// optionally filtered by a name substring. Candidates for code caves.
// Usage: ... -postScript Unreferenced.java [nameFilter] [minBytes]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class Unreferenced extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] a = getScriptArgs();
        String filter = a.length > 0 ? a[0] : "";
        long min = a.length > 1 ? Long.parseLong(a[1]) : 64;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (f.isExternal() || f.isThunk()) continue;
            String n = f.getName(true);
            if (!filter.isEmpty() && !n.contains(filter)) continue;
            long size = f.getBody().getNumAddresses();
            if (size < min) continue;
            int real = 0;
            for (ghidra.program.model.symbol.Reference r : getReferencesTo(f.getEntryPoint()))
                if (r.getFromAddress().getOffset() < 0x101000000L) real++;  // skip symbol-table/LINKEDIT refs
            if (real == 0)
                System.out.println("UNREF " + f.getEntryPoint() + " " + size + " " + n);
        }
    }
}
