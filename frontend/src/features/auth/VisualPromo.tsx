import { Building2, TrendingUp, Users, ShieldCheck } from "lucide-react";

export function VisualPromo() {
  return (
    <div className="relative hidden w-full flex-col justify-between overflow-hidden bg-slate-950 p-12 text-white lg:flex lg:w-1/2 xl:w-7/12">
      {/* Background elegant gradient mesh */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(37,99,235,0.25),transparent_45%),radial-gradient(circle_at_bottom_left,rgba(99,102,241,0.15),transparent_50%)]" />
      <div className="absolute top-1/4 left-1/4 h-72 w-72 rounded-full bg-blue-600/10 blur-3xl animate-pulse" />
      <div className="absolute bottom-1/4 right-1/4 h-80 w-80 rounded-full bg-indigo-600/10 blur-3xl animate-pulse" style={{ animationDelay: "2s" }} />

      {/* Brand logo & title */}
      <div className="relative z-10 flex items-center gap-3">
        <span className="flex size-10 items-center justify-center rounded-xl bg-blue-600 shadow-lg shadow-blue-500/30 text-white">
          <Building2 className="size-6" />
        </span>
        <span className="text-xl font-bold tracking-tight bg-gradient-to-r from-white to-slate-300 bg-clip-text text-transparent">PropManager</span>
      </div>

      {/* Middle: Glassmorphic dashboard mockup */}
      <div className="relative z-10 my-auto max-w-lg space-y-6">
        <div className="space-y-4">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-400 border border-blue-500/20 backdrop-blur-md">
            <ShieldCheck className="size-3.5" /> Co-living Management Suite
          </span>
          <h1 className="text-4xl font-extrabold tracking-tight leading-tight lg:text-5xl">
            Simplify PG Operations. <br />
            <span className="bg-gradient-to-r from-blue-400 via-indigo-300 to-white bg-clip-text text-transparent">
              Amplify Your Returns.
            </span>
          </h1>
          <p className="text-base text-slate-400 max-w-md">
            The complete operating system for modern hostels and PG properties. Scale tenant enrollment, automate billing, and track complaints in real-time.
          </p>
        </div>

        {/* Floating Glassmorphic cards */}
        <div className="relative pt-6">
          {/* Card 1: Occupancy Status */}
          <div className="transform rounded-2xl border border-white/10 bg-white/5 p-5 shadow-2xl backdrop-blur-xl transition-all duration-500 hover:-translate-y-1 hover:border-white/15">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Occupancy status</span>
              <span className="text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full flex items-center gap-1">
                <TrendingUp className="size-3" /> +8.4%
              </span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold tracking-tight text-white">81.6%</span>
              <span className="text-sm text-slate-400">98/120 occupied beds</span>
            </div>
            <div className="mt-3 h-2 w-full rounded-full bg-white/10 overflow-hidden">
              <div className="h-full rounded-full bg-blue-500" style={{ width: "81.6%" }} />
            </div>
          </div>

          {/* Card 2: Floating activity stat */}
          <div className="absolute -bottom-10 -right-6 hidden sm:flex transform items-center gap-3 rounded-xl border border-white/10 bg-white/10 p-3 shadow-xl backdrop-blur-md transition-all duration-500 hover:scale-105">
            <div className="flex size-8 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-400">
              <Users className="size-4.5" />
            </div>
            <div>
              <p className="text-xs font-semibold text-white">Rahul S. Checked-in</p>
              <p className="text-[10px] text-slate-400">Unit 105B · Just now</p>
            </div>
          </div>
        </div>
      </div>

      {/* Footer info */}
      <div className="relative z-10 flex items-center justify-between text-xs text-slate-500 border-t border-slate-800/60 pt-6">
        <p>© 2026 PropManager Technologies.</p>
        <div className="flex gap-4">
          <a href="#" className="hover:text-slate-400">Terms</a>
          <a href="#" className="hover:text-slate-400">Privacy Policy</a>
        </div>
      </div>
    </div>
  );
}
