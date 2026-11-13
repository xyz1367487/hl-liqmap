const fs=require('node:fs'),path=require('node:path');
module.exports=new Function('module',fs.readFileSync(path.join(__dirname,'../chart-core.js'),'utf8')+';return module.exports;')({exports:{}});
