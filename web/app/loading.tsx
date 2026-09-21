/**
 * Route-level skeleton. Panels pulse in the shape of the page that is coming,
 * so navigation never flashes a blank main. Reduced-motion users get a static
 * skeleton via the globals.css media query.
 */
export default function Loading() {
  return (
    <div className="animate-fade-in space-y-5" aria-busy="true" aria-label="Loading">
      <div className="space-y-2">
        <div className="h-7 w-48 animate-pulse-dot rounded-lg bg-edge/50" />
        <div className="h-4 w-80 max-w-full animate-pulse-dot rounded-lg bg-edge/40" />
      </div>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-edge bg-edge/40 sm:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="h-20 animate-pulse-dot bg-panel/80" />
        ))}
      </div>
      <div className="h-14 animate-pulse-dot rounded-xl border border-edge bg-panel/60" />
      <div className="h-72 animate-pulse-dot rounded-xl border border-edge bg-panel/60" />
    </div>
  );
}
