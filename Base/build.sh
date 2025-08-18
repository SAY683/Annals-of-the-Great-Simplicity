#!/bin/sh

# 我们现在已经在 "Base" 目录里了。
# 所有的源文件路径都需要使用 "../" 来返回到项目根目录。

# 1. 确保目标目录存在 (路径是相对于当前 "Base" 目录的)
mkdir -p Miscellanies

# # 2. 从项目根目录 ("../") 复制所有PDF文件到当前目录下的 "Miscellanies/"
# echo "Copying root PDFs from ../ to ./Miscellanies..."
# cp ../*.pdf Miscellanies/

# 3. 从项目根目录的 "Miscellanies" 文件夹 ("../Miscellanies/") 复制所有PDF
echo "Copying source Miscellanies PDFs from ../Miscellanies/ to ./Miscellanies..."
cp ../Miscellanies/*.pdf Miscellanies/

echo "Build script finished successfully."