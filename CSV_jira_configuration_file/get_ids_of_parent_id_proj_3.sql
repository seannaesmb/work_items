--drop temp table temp_results

--CREATE TEMP TABLE temp_results AS
--SELECT id, project_id, parent_id, type_id
--FROM work_packages

SELECT
    t1.id AS t1_id,
    t1.parent_id AS t1_parent,
    t1.project_id as t1_project,
    t1.type_id as t1_type_id,
    t2.id AS t2_id,
    t2.parent_id AS t2_parent,
    t2.project_id as t2_project,
    t2.type_id as t2_type_id
FROM
    work_packages t1
    INNER JOIN temp_results t2 ON t2.parent_id = t1.id
    and t2.parent_id is not null
    and t1.project_id = 3