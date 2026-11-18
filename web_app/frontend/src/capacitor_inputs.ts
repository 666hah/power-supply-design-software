import type { Spec } from './types';

export type ImpedanceCurve = { points: [number, number, number][]; source?: string };
export type CapacitorMode = 'fixed' | 'curve';
export type CapacitorSide = 'input' | 'output';
export type NominalKey = 'C' | 'ESR' | 'ESL';
export type Capacitor = Record<NominalKey, number> & {
  impedance_mode?: CapacitorMode;
  impedance_curve?: ImpedanceCurve;
  thermal_resistance_K_per_W?: number;
};

export type CapacitorModelEdit = { side: CapacitorSide; railIndex?: number; rows: Capacitor[] };

export function capacitorRows(spec: Spec, side: CapacitorSide, scalarFallback?: Spec): Capacitor[] {
  const values = spec[`${side}_capacitors`];
  if (Array.isArray(values)) return values;
  const p = scalarFallback ? { ...scalarFallback, ...spec } : spec;
  if (side === 'input') {
    return [{ C: p.Cin1, ESR: p.Rcin1, ESL: p.ESLin1 },
      ...(p.cin2_enable ? [{ C: p.Cin2, ESR: p.Rcin2, ESL: p.ESLin2 }] : [])];
  }
  return [{ C: p.C_out, ESR: p.Rc, ESL: p.ESL },
    ...(p.cout2_enable ? [{ C: p.C_out2, ESR: p.Rc2, ESL: p.ESL2 }] : [])];
}

export function capacitorMode(capacitor: Capacitor | undefined): CapacitorMode {
  return capacitor?.impedance_mode ?? (capacitor?.impedance_curve ? 'curve' : 'fixed');
}

export function capacitorRef(side: CapacitorSide, index: number, railIndex?: number): string {
  const n = index + 1;
  if (side === 'input') return `C_IN${n}`;
  if (railIndex === undefined) return `C_O${n}`;
  return `C_O${railIndex + 1}${n <= 26 ? String.fromCharCode(64 + n) : `_${n}`}`;
}
