import type { OrderRepository } from "../../domain/ports/OrderRepository";

export class PrismaOrderRepository implements OrderRepository {
  async save(_id: string): Promise<void> {}
}
