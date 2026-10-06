"""Informational matchups, preserving names as recorded at the time of play."""
from flask import abort


def rounds_by_challenge(db):
    grouped = {}
    people_by_round = {}
    for person in db.execute('SELECT * FROM round_people ORDER BY id'):
        people_by_round.setdefault(person['round_id'], []).append(dict(person))
    for row in db.execute('SELECT * FROM rounds ORDER BY challenge_id, round_number, id'):
        match = dict(row)
        for side in ('left', 'right'):
            match[side + '_people'] = [person for person in people_by_round.get(row['id'], []) if person['side'] == side]
        grouped.setdefault(row['challenge_id'], []).append(match)
    return grouped


def selected_sides(db, form, previous=None):
    """Validate live selections and any preserved, deleted entrants on an edit."""
    sides = {}
    all_people = set()
    for side in ('left', 'right'):
        team_value = form.get(side + '_team_id', '')
        team_id, team_name = None, ''
        if team_value == 'archived':
            if not previous or previous[side + '_team_id'] is not None or not previous[side + '_team_name']:
                raise ValueError('El equipo seleccionado no es válido.')
            team_name = previous[side + '_team_name']
        elif team_value:
            team = db.execute('SELECT * FROM teams WHERE id=?', (parse_id(team_value),)).fetchone()
            if team is None:
                raise ValueError('El equipo seleccionado ya no existe.')
            team_id, team_name = team['id'], team['name']
        people = []
        for value in form.getlist(side + '_people'):
            if value.startswith('archived:'):
                person_id = parse_id(value.removeprefix('archived:'))
                person = db.execute('SELECT * FROM round_people WHERE id=? AND round_id=? AND side=? AND participant_id IS NULL',
                                    (person_id, previous['id'] if previous else None, side)).fetchone()
                if person is None:
                    raise ValueError('La persona seleccionada no es válida.')
                identity = ('archived', person_id)
                participant_id, name = None, person['participant_name']
            else:
                participant_id = parse_id(value)
                person = db.execute('SELECT * FROM participants WHERE id=?', (participant_id,)).fetchone()
                if person is None:
                    raise ValueError('Una de las personas seleccionadas ya no existe.')
                identity = ('participant', participant_id)
                name = person['name']
            if identity in all_people:
                raise ValueError('Una persona no puede aparecer dos veces ni en ambos lados de la ronda.')
            all_people.add(identity)
            people.append((participant_id, name))
        if not team_name and not people:
            raise ValueError('Selecciona un equipo o al menos una persona en cada lado.')
        sides[side] = {'team_id': team_id, 'team_name': team_name, 'people': people}
    if sides['left']['team_id'] is not None and sides['left']['team_id'] == sides['right']['team_id']:
        raise ValueError('El mismo equipo no puede competir en ambos lados.')
    return sides


def parse_id(value):
    try:
        identity = int(value)
    except (ValueError, TypeError):
        raise ValueError('Selecciona una persona o equipo válido.') from None
    if not 1 <= identity <= 1000000:
        raise ValueError('Selecciona una persona o equipo válido.')
    return identity


def save_round(db, form, fields, previous=None):
    """Write the matchup and all contestants in the caller's transaction."""
    sides = selected_sides(db, form, previous)
    values = (*fields, sides['left']['team_id'], sides['right']['team_id'],
              sides['left']['team_name'], sides['right']['team_name'])
    if previous:
        cursor = db.execute('''UPDATE rounds SET round_number=?, format=?, outcome=?,
            left_team_id=?, right_team_id=?, left_team_name=?, right_team_name=?, revision=revision+1
            WHERE id=? AND revision=?''', (*values, previous['id'], parse_id(form.get('revision'))))
        if cursor.rowcount != 1:
            abort(409)
        round_id = previous['id']
        db.execute('DELETE FROM round_people WHERE round_id=?', (round_id,))
    else:
        cursor = db.execute('''INSERT INTO rounds(round_number, format, outcome,
            left_team_id, right_team_id, left_team_name, right_team_name, challenge_id, submission_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (*values, parse_id(form.get('challenge_id')), form.get('submission_key')))
        round_id = cursor.lastrowid
    for side in ('left', 'right'):
        db.executemany('INSERT INTO round_people(round_id, side, participant_id, participant_name) VALUES (?, ?, ?, ?)',
                       [(round_id, side, participant_id, name) for participant_id, name in sides[side]['people']])
