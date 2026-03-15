export function getCachedResource<T>(
  key: string,
  cache: Map<string, T>,
  inFlight: Map<string, Promise<T>>,
  loader: () => Promise<T>,
): Promise<T> {
  const cached = cache.get(key);
  if (cached !== undefined) {
    return Promise.resolve(cached);
  }

  const pending = inFlight.get(key);
  if (pending) {
    return pending;
  }

  const request = loader()
    .then((value) => {
      cache.set(key, value);
      return value;
    })
    .finally(() => {
      inFlight.delete(key);
    });

  inFlight.set(key, request);
  return request;
}

export function seedCachedResource<T>(
  key: string,
  cache: Map<string, T>,
  value: T,
): void {
  cache.set(key, value);
}

export function clearCachedResource<T>(
  cache: Map<string, T>,
  inFlight: Map<string, Promise<T>>,
): void {
  cache.clear();
  inFlight.clear();
}
