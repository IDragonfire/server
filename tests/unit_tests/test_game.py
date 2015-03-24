import logging
from unittest import mock

import pytest
from trueskill import Rating

from src.games.game import Game, GameState, GameError
from src.gameconnection import GameConnection, GameConnectionState


@pytest.fixture()
def game(db):
    mock_parent = mock.Mock()
    mock_parent.db = db
    return Game(42, mock_parent)


def test_initialization(game):
    assert game.state == GameState.INITIALIZING


def test_instance_logging(db):
    logger = logging.getLogger('{}.5'.format(Game.__qualname__))
    logger.info = mock.Mock()
    mock_parent = mock.Mock()
    mock_parent.db = db
    game = Game(5, mock_parent)
    logger.info.assert_called_with("{} created".format(game))


@pytest.fixture
def game_connection(state=GameConnectionState.initializing, player=None):
    gc = mock.create_autospec(spec=GameConnection)
    gc.state = state
    gc.player = player
    return gc


def add_connected_player(game: Game, player):
    game.add_game_connection(game_connection(state=GameConnectionState.connected_to_host, player=player))


def add_connected_players(game: Game, players):
    for player in players:
        add_connected_player(game, player)


def test_set_player_option(game, players, game_connection):
    game.state = GameState.LOBBY
    game_connection.player = players.hosting
    game_connection.state = GameConnectionState.connected_to_host
    game.add_game_connection(game_connection)
    assert game.players == {players.hosting}
    game.set_player_option(players.hosting.id, 'Team', 1)
    assert game.get_player_option(players.hosting.id, 'Team') == 1
    assert game.teams == {1: [players.hosting]}
    game.set_player_option(players.hosting.id, 'StartSpot', 1)
    game.get_player_option(players.hosting.id, 'StartSpot') == 1


def test_add_game_connection(game: Game, players, game_connection):
    game.state = GameState.LOBBY
    game_connection.player = players.hosting
    game_connection.state = GameConnectionState.connected_to_host
    game.add_game_connection(game_connection)
    assert players.hosting in game.players


def test_add_game_connection_throws_if_not_connected_to_host(game: Game, players, game_connection):
    game.state = GameState.LOBBY
    game_connection.player = players.hosting
    game_connection.state = GameConnectionState.initialized
    with pytest.raises(GameError):
        game.add_game_connection(game_connection)

    assert players.hosting not in game.players


def test_remove_game_connection(game: Game, players, game_connection):
    game.state = GameState.LOBBY
    game_connection.player = players.hosting
    game_connection.state = GameConnectionState.connected_to_host
    game.add_game_connection(game_connection)
    game.remove_game_connection(game_connection)
    assert players.hosting not in game.players


def test_game_end_when_no_more_connections(game: Game, game_connection):
    game.state = GameState.LOBBY
    game.on_game_end = mock.Mock()
    game_connection.state = GameConnectionState.connected_to_host
    game.add_game_connection(game_connection)
    game.remove_game_connection(game_connection)
    game.on_game_end.assert_any_call()


def test_game_launch_freezes_players(game: Game, players):
    conn1 = game_connection()
    conn1.state = GameConnectionState.connected_to_host
    conn1.player = players.hosting
    conn2 = game_connection()
    conn2.player = players.joining
    conn2.state = GameConnectionState.connected_to_host
    game.state = GameState.LOBBY
    game.add_game_connection(conn1)
    game.add_game_connection(conn2)
    game.launch()
    assert game.state == GameState.LIVE
    assert game.players == {players.hosting, players.joining}
    game.remove_game_connection(conn1)
    assert game.players == {players.hosting, players.joining}


def test_game_teams_represents_active_teams(game: Game, players):
    game.state = GameState.LOBBY
    add_connected_players(game, [players.hosting, players.joining])
    game.set_player_option(players.hosting.id, 'Team', 1)
    game.set_player_option(players.joining.id, 'Team', 2)
    assert game.teams == {1: [players.hosting],
                          2: [players.joining]}


def test_compute_rating_computes_global_ratings(game: Game, players):
    game.state = GameState.LOBBY
    players.hosting.global_rating = Rating(1500, 250)
    players.joining.global_rating = Rating(1500, 250)
    add_connected_players(game, [players.hosting, players.joining])
    game.launch()
    game.add_result(players.hosting, 1)
    game.add_result(players.joining, 0)
    game.set_player_option(players.hosting.id, 'Team', 1)
    game.set_player_option(players.joining.id, 'Team', 2)
    groups = game.compute_rating()
    assert players.hosting in groups[0]
    assert players.joining in groups[1]


def test_compute_rating_computes_ladder_ratings(game: Game, players):
    game.state = GameState.LOBBY
    players.hosting.ladder_rating = Rating(1500, 250)
    players.joining.ladder_rating = Rating(1500, 250)
    add_connected_players(game, [players.hosting, players.joining])
    game.launch()
    game.add_result(players.hosting, 1)
    game.add_result(players.joining, 0)
    game.set_player_option(players.hosting.id, 'Team', 1)
    game.set_player_option(players.joining.id, 'Team', 2)
    groups = game.compute_rating(rating='ladder')
    assert players.hosting in groups[0]
    assert players.joining in groups[1]


def test_compute_rating_balanced_teamgame(game: Game, create_player):
    game.state = GameState.LOBBY
    players = [
        (create_player(**info), result, team) for info, result, team in [
            (dict(login='Paula_Bean', id=1, global_rating=Rating(1500, 250.7)), 0, 1),
            (dict(login='Some_Guy', id=2, global_rating=Rating(1700, 120.1)), 0, 1),
            (dict(login='Some_Other_Guy', id=3, global_rating=Rating(1200, 72.02)), 0, 2),
            (dict(login='That_Person', id=4, global_rating=Rating(1200, 72.02)), 0, 2),
        ]
    ]
    add_connected_players(game, [player for player, _, _ in players])
    for player, _, team in players:
        game.set_player_option(player.id, 'Team', team)
    game.launch()
    for player, result, _ in players:
        game.add_result(player, result)
    result = game.compute_rating()
    for team in result:
        for player, new_rating in team.items():
            assert player in game.players
            assert new_rating != player.global_rating
