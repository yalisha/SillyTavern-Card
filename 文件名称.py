import os

def get_filenames_without_extension(folder_path):
  """
  获取指定文件夹下的所有文件名（去除后缀）。

  Args:
    folder_path: 目标文件夹的路径。

  Returns:
    一个包含所有文件名（去除后缀）的列表。
  """
  filenames = []
  for f in os.scandir(folder_path):
    if f.is_file():  # 确保是文件
      filename = f.name
      name_without_extension = os.path.splitext(filename)[0]  # 去除后缀
      filenames.append(name_without_extension)
  return filenames

# 替换成你的文件夹路径！
folder_path = "/Users/mac/Documents/SIllyTavern_test/lorebook_script/Mywives3/world"

filenames = get_filenames_without_extension(folder_path)

if filenames:
  print("文件名（去除后缀）列表：")
  for filename in filenames:
    print(filename)
else:
  print("该文件夹下没有文件。")
