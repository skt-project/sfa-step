// Test environment setup.
//
// jsdom does not reliably expose `localStorage` (its Storage is gated on a
// non-opaque origin), yet the auth store and API client depend on it. Install a
// deterministic in-memory implementation so every test file starts from a clean,
// isolated store regardless of the jsdom origin.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  [name: string]: unknown;

  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
}

const mem = new MemoryStorage();
try {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: mem,
  });
} catch {
  (globalThis as unknown as { localStorage: Storage }).localStorage = mem;
}
