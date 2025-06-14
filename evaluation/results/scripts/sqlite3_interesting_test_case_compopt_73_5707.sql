�
PRAGMA foreign_keys=ON;
PRAGMA full_column_names=FALSE;
PRAGMA writable_schema=FALSE;
PRAGMA compile_options=FALSE;
	CREATE TABLE IF NOT EXISTS tz (
		cz TEXT,
		dz TEXT,
		ez TEXT,
		PRIMARY KEY (cz, dz)
	);
	INSERT INTO tz VALUES ('N', 'Gc', '');
	INSERT INTO tz VALUES ('Sz', 'lq', 'p');
	INSERT INTO tz VALUES ('', '', '');
	INSERT INTO tz VALUES ('es', '#0', 'V');
	INSERT INTO tz VALUES ('', '', '');
	DELETE FROM tz WHERE cz=')' AND cz='' AND cz='a';
	DELETE FROM tz WHERE cz='0=' AND cz='' AND cz='';
	DELETE FROM tz WHERE cz=' )' AND cz='P2' AND cz='92';
	DELETE FROM tz WHERE cz='@Z' AND cz='p' AND cz='4^';
	DELETE FROM tz WHERE cz='xz' AND cz='|F' AND cz='';
	UPDATE tz SET dz='Lo', ez='', cz='' WHERE cz='Lo' AND cz='' AND cz='';
	UPDATE tz SET dz='36', ez='', cz='0d1' WHERE cz='36' AND cz='' AND cz='0d1';
	UPDATE tz SET dz=';'I', ez='"', cz='' WHERE cz=';'I' AND cz='"' AND cz='';
	UPDATE tz SET dz='Av', ez='kL=', cz='' WHERE cz='Av' AND cz='kL=' AND cz='';
	UPDATE tz SET dz='~-7', ez='3j', cz='WKV' WHERE cz='~-7' AND cz='3j' AND cz='WKV';
	SELECT cz, dz, ez FROM tz  ORDER BY   OFFSET 7;
	SELECT cz, ez FROM tz   LIMIT 5 ;
	SELECT cz, dz FROM tz WHERE cz LIKE '%' AND dz='0'   ;
	SELECT cz, ez FROM tz WHERE cz LIKE '%' AND dz='i' ORDER BY dz LIMIT 6 OFFSET 4;
	SELECT cz FROM tz WHERE cz LIKE 't%' AND dz='5' ORDER BY ez  ;
	SELECT * FROM tz;
	DELETE FROM tz WHERE cz=?;
	UPDATE tz SET dz=? WHERE cz=?;
	CREATE TRIGGER IF NOT EXISTS trigz AFTER INSERT ON tz BEGIN SELECT RAISE(ABORT,'This is an error message!'); END;
	DROP TRIGGER IF EXISTS trigz;
	CREATE VIEW IF NOT EXISTS viewz AS SELECT * FROM tz;
	DROP VIEW IF EXISTS viewz;
	CREATE INDEX IF NOT EXISTS idxz ON tz (cz, dz, ez);
	DROP INDEX IF EXISTS idxz;
	COMMIT TRANSACTION;
