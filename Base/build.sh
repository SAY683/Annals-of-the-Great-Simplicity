#!/bin/sh

# 这个脚本现在是从项目根目录被调用的。
# 所以路径不再需要 "../"。

# 1. 确保目标目录存在
mkdir -p Base/Miscellanies

# 2. 从根目录复制所有PDF
echo "Copying root PDFs to Base/Miscellanies..."
cp *.pdf Base/Miscellanies/

# 3. 从根目录的 Miscellanies 文件夹复制所有PDF
echo "Copying source Miscellanies PDFs to Base/Miscellanies..."

# 4. 告诉脚本复制 Miscellanies 文件夹里的所有PDF
cp Miscellanies/*.pdf Base/Miscellanies/

echo "File copy script finished successfully."