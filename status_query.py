import sqlite3
c=sqlite3.connect('/vol4/1000/docker/music-pipeline/data/music.db')
for q in ["select count(*) from tracks", "select status,count(*) from tracks group by status", "select status,count(*) from jobs group by status", "select source_path,error from jobs where status='failed' order by id desc limit 5"]:
 print(c.execute(q).fetchall())
