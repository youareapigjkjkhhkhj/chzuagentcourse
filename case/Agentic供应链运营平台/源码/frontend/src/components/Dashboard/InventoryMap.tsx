import styles from './InventoryMap.module.css'

interface InventoryItem {
  sku: string
  product_name: string
  warehouse_name: string
  quantity: number
}

interface Product {
  sku: string
  name: string
  category: string
  reorder_point: number
}

interface InventoryMapProps {
  inventory: InventoryItem[]
  products: Product[]
}

export function InventoryMap({ inventory, products }: InventoryMapProps) {
  const getRiskColor = (quantity: number, reorderPoint: number) => {
    if (quantity < reorderPoint) return 'critical'
    if (quantity < reorderPoint * 1.5) return 'low'
    if (quantity > reorderPoint * 3) return 'excess'
    return 'normal'
  }

  const warehouses = [...new Set(inventory.map((i) => i.warehouse_name))]

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>库存热力图</h3>
      <div className={styles.map}>
        <div className={styles.headerRow}>
          <div className={styles.cornerCell}>SKU</div>
          {warehouses.map((w) => (
            <div key={w} className={styles.headerCell}>{w.split(' - ')[1] || w}</div>
          ))}
        </div>
        {products.slice(0, 5).map((product) => {
          const productInventory = inventory.filter((i) => i.sku === product.sku)

          return (
            <div key={product.sku} className={styles.row}>
              <div className={styles.skuCell}>
                <span className={styles.skuName}>{product.name.split(' ').slice(0, 2).join(' ')}</span>
                <span className={styles.skuCode}>{product.sku}</span>
              </div>
              {warehouses.map((wh) => {
                const item = productInventory.find((i) => i.warehouse_name === wh)
                const qty = item?.quantity || 0
                const cellRisk = getRiskColor(qty, Math.floor(product.reorder_point / 3))

                return (
                  <div
                    key={wh}
                    className={`${styles.cell} ${styles[cellRisk]}`}
                    title={`${wh}: ${qty} 单位`}
                  >
                    <span className={styles.cellValue}>{qty}</span>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
      <div className={styles.legend}>
        <div className={styles.legendItem}>
          <div className={`${styles.legendDot} ${styles.critical}`} />
          <span>紧急</span>
        </div>
        <div className={styles.legendItem}>
          <div className={`${styles.legendDot} ${styles.low}`} />
          <span>偏低</span>
        </div>
        <div className={styles.legendItem}>
          <div className={`${styles.legendDot} ${styles.normal}`} />
          <span>正常</span>
        </div>
        <div className={styles.legendItem}>
          <div className={`${styles.legendDot} ${styles.excess}`} />
          <span>过剩</span>
        </div>
      </div>
    </div>
  )
}
