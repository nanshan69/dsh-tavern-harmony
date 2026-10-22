// 门后面真正的酒馆 host。
//
// 单独一个文件是刻意的：`ctx.plugin()` 需要的是「插件模块」的形态
// （导出的 name / inject / apply），而这里的转发让 gate 完全不认识酒馆内部结构。
// 换上游版本时只替换 dsh-tavern-host 包，这个文件不用改。
export * from 'dsh-tavern-host'
