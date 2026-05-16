export interface OrderRepository {
  save(id: string): Promise<void>;
}
