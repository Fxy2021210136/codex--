export const readJson=<T,>(key:string,fallback:T):T=>{
  try{return JSON.parse(localStorage.getItem(key)??'') as T}catch{return fallback}
}
