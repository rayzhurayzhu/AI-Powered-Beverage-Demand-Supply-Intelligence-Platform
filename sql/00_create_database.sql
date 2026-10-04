-- Run in MySQL Workbench or at the mysql> prompt, not in PowerShell.
CREATE DATABASE IF NOT EXISTS beverage_intelligence
  CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE beverage_intelligence;
SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;
