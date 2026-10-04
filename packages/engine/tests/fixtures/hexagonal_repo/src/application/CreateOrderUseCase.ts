import type { OrderRepository } from "../domain/ports/OrderRepository";

export class CreateOrderUseCase {
  constructor(private readonly repo: OrderRepository) {}
  async execute(id: string): Promise<void> {
    await this.repo.save(id);
  }
}
