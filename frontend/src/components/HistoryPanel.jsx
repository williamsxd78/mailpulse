import { useEffect, useState } from "react";
import { History, Trash2, RotateCcw, Clock } from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getHistory, getBatch, deleteBatch } from "@/lib/api";

export function HistoryPanel({ open, onOpenChange, onLoad, refreshKey }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setItems(await getHistory());
    } catch {
      toast.error("Failed to load history");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) load();
  }, [open, refreshKey]);

  const handleLoad = async (id) => {
    try {
      const batch = await getBatch(id);
      onLoad(batch);
      onOpenChange(false);
      toast.success(`Loaded "${batch.name}"`);
    } catch {
      toast.error("Failed to load batch");
    }
  };

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    try {
      await deleteBatch(id);
      setItems((prev) => prev.filter((b) => b.id !== id));
      toast.success("Batch deleted");
    } catch {
      toast.error("Failed to delete");
    }
  };

  const fmt = (iso) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>
        <Button data-testid="history-drawer-toggle" variant="outline" size="sm" className="gap-1.5 h-9 border-border/60 bg-black/20 hover:bg-black/40">
          <History size={15} /> History
        </Button>
      </SheetTrigger>
      <SheetContent data-testid="history-panel" side="right" className="w-full sm:max-w-md bg-card border-border/60 mp-scroll">
        <SheetHeader className="text-left">
          <SheetTitle className="font-display flex items-center gap-2 text-foreground">
            <History size={18} className="text-emerald-400" /> Check History
          </SheetTitle>
          <SheetDescription className="text-xs text-muted-foreground">
            Past validation runs — click any run to reload its results.
          </SheetDescription>
        </SheetHeader>

        <ScrollArea className="h-[calc(100vh-90px)] mt-4 -mr-4 pr-4 mp-scroll">
          {loading ? (
            <p className="text-sm text-muted-foreground font-mono py-8 text-center">Loading…</p>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center">
              <Clock className="text-muted-foreground opacity-40" size={28} />
              <p className="text-sm text-muted-foreground">No validation runs yet</p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {items.map((b) => {
                const rate = b.total ? Math.round((b.deliverable_count / b.total) * 100) : 0;
                return (
                  <div
                    key={b.id}
                    data-testid={`history-item-${b.id}`}
                    onClick={() => handleLoad(b.id)}
                    className="cursor-pointer rounded-lg border border-border/50 bg-black/20 hover:bg-black/40 hover:border-emerald-800/50 p-3 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-display text-sm font-medium text-foreground truncate">{b.name}</p>
                        <p className="text-[11px] text-muted-foreground font-mono mt-0.5">{fmt(b.created_at)}</p>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-emerald-400" onClick={(e) => { e.stopPropagation(); handleLoad(b.id); }}>
                          <RotateCcw size={13} />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-rose-400" onClick={(e) => handleDelete(b.id, e)}>
                          <Trash2 size={13} />
                        </Button>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 mt-2.5 text-xs font-mono">
                      <span className="text-emerald-400">{b.deliverable_count} valid</span>
                      <span className="text-rose-400">{b.invalid_count} invalid</span>
                      <span className="text-muted-foreground ml-auto">{rate}% deliverable</span>
                    </div>
                    <div className="mt-1.5 h-1 w-full rounded-full bg-rose-900/40 overflow-hidden">
                      <div className="h-full bg-emerald-500/70" style={{ width: `${rate}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
