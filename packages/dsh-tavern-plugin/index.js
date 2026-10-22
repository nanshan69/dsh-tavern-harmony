// dsh-tavern-plugin 的 host 半边：空实现。只为了让 client bundle 有一个 loader 行，
// 从而被 dsh-client-modules 扫描并挂到页面上。真正的 host 逻辑在 dsh-tavern-host 里，
// 由 dsh-tavern-gate 在运行时加载。
export const name = 'dsh-tavern-client-row'
export const inject = []
export function apply() {}
