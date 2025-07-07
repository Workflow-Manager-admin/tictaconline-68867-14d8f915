"""
Tic-Tac-Toe Backend REST API

This backend provides endpoints for:
- Starting a new game (human vs human or human vs AI)
- Making a move
- Retrieving current game state
- Tracking scores

Framework: FastAPI (for clarity, maintainability, and OpenAPI support)
"""

import random
import uuid
from typing import List, Optional, Dict, Literal

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ----- Data Models -----

class GameMode(str):
    """Valid game types."""
    AI = "human_vs_ai"
    HUMAN = "human_vs_human"

class GameStatus(str):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    TIE = "tie"
    FINISHED = "finished"

class MoveResult(str):
    VALID = "valid"
    INVALID = "invalid"
    WIN = "win"
    TIE = "tie"

class Player(str):
    X = "X"
    O = "O"

def opponent(player: str) -> str:
    return Player.O if player == Player.X else Player.X

# For simplicity use in-memory dict for games. In production, use a DB.
games: Dict[str, dict] = {}

class MoveRequest(BaseModel):
    """Request model for making a move."""
    position: int = Field(..., ge=0, le=8, description="Position 0-8 on the board")
    player: Literal["X", "O"] = Field(..., description="Player making the move")

class StartGameRequest(BaseModel):
    """Request model for starting a game."""
    mode: GameMode = Field(..., description="Game mode: human_vs_human or human_vs_ai")
    player_starts: Optional[Literal["X", "O"]] = Field(None, description="(AI mode): Which player starts? Default: X")

class GameStateResponse(BaseModel):
    """Game state representation."""
    game_id: str
    board: List[Optional[str]] = Field(..., max_items=9, min_items=9, description="List of 9 items: X, O, or null")
    next_player: Optional[str] = Field(None, description="X or O. None if game over.")
    status: GameStatus
    winner: Optional[str] = Field(None, description="X or O if won, None otherwise")
    mode: GameMode
    scores: Dict[str, int]
    moves: int

# ----- FastAPI Init -----

app = FastAPI(
    title="Tic Tac Toe Backend API",
    description="Classic Tic-Tac-Toe backend/game state management. Start games, play moves, see state, play against the computer or a friend.",
    version="1.0.0",
    openapi_tags=[
        {"name": "game", "description": "Game management and play endpoints"},
    ]
)

# Allow all CORS for frontend connectivity in dev:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Game Logic -----

def check_winner(board: List[Optional[str]]) -> Optional[str]:
    """Check if X or O won, else None."""
    wins = [
        [0,1,2],[3,4,5],[6,7,8],
        [0,3,6],[1,4,7],[2,5,8],
        [0,4,8],[2,4,6]
    ]
    for p in ["X","O"]:
        if any(all(board[i]==p for i in w) for w in wins):
            return p
    return None

def is_full(board: List[Optional[str]]) -> bool:
    return all(cell is not None for cell in board)

def valid_move(board: List[Optional[str]], position: int) -> bool:
    return 0 <= position < 9 and board[position] is None

def ai_move(board: List[Optional[str]]) -> int:
    """Very basic AI: first try to win, then block, else random."""
    # Try to win
    for i in range(9):
        if board[i] is None:
            test = board[:]
            test[i] = "O"
            if check_winner(test) == "O":
                return i
    # Try to block
    for i in range(9):
        if board[i] is None:
            test = board[:]
            test[i] = "X"
            if check_winner(test) == "X":
                return i
    # Center
    if board[4] is None:
        return 4
    # Corners or random available
    open_spots = [i for i,v in enumerate(board) if v is None]
    return random.choice(open_spots)

# ----- In-Memory Score Storage (per session) -----
global_scores = {"X": 0, "O": 0, "games": 0}

def update_scores(winner: Optional[str]):
    global_scores["games"] += 1
    if winner in ["X", "O"]:
        global_scores[winner] += 1

# ----- API Endpoints -----

# PUBLIC_INTERFACE
@app.post("/start", tags=["game"], summary="Start a new Tic-Tac-Toe game", response_model=GameStateResponse)
def start_game(req: StartGameRequest = Body(..., description="Game start configuration")):
    """
    Start a new Tic-Tac-Toe game.

    - mode: 'human_vs_ai' (player vs computer), 'human_vs_human' (player vs player)
    - player_starts: Optional; X or O (defaults to X). When playing vs AI, player_starts==O means AI starts.
    
    Returns a game id and initial state.
    """
    game_id = str(uuid.uuid4())
    mode = req.mode
    board: List[Optional[str]] = [None] * 9
    player_starts = req.player_starts or "X"
    next_player = player_starts

    state = {
        "game_id": game_id,
        "board": board,
        "next_player": next_player,
        "status": GameStatus.IN_PROGRESS,
        "winner": None,
        "mode": mode,
        "moves": 0,
        "scores": dict(global_scores)
    }

    # If AI starts, make AI move
    if mode == GameMode.AI and next_player == "O":
        pos = ai_move(board)
        board[pos] = "O"
        state["moves"] += 1
        winner = check_winner(board)
        if winner:
            state["status"] = GameStatus.FINISHED
            state["winner"] = winner
            update_scores(winner)
        elif is_full(board):
            state["status"] = GameStatus.TIE
        else:
            state["next_player"] = "X"

    games[game_id] = state
    return GameStateResponse(**state)

# PUBLIC_INTERFACE
@app.post("/move/{game_id}", tags=["game"], summary="Make a move in a game", response_model=GameStateResponse)
def make_move(game_id: str, move: MoveRequest = Body(..., description="The move - position (0-8) and player (X or O)")):
    """
    Make a move on the game board.

    - Provide position (0-8) and player ("X" or "O").
    - For human_vs_ai, if player's move is valid and game is not finished, AI will play immediately after.
    Returns updated game state and winner if game ends. Throws HTTP 400 if invalid move.
    """
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    game = games[game_id]
    board = game["board"]
    status = game["status"]
    mode = game["mode"]

    if status != GameStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Game already finished")

    if move.player != game["next_player"]:
        raise HTTPException(status_code=400, detail=f"It is not player {move.player}'s turn")

    if not valid_move(board, move.position):
        raise HTTPException(status_code=400, detail="Invalid move position")

    # Make player move
    board[move.position] = move.player
    game["moves"] += 1

    winner = check_winner(board)
    if winner:
        game["status"] = GameStatus.FINISHED
        game["winner"] = winner
        update_scores(winner)
    elif is_full(board):
        game["status"] = GameStatus.TIE
    else:
        game["next_player"] = opponent(move.player)

    # If AI needs to play and game is still on
    if mode == GameMode.AI and game["next_player"] == "O" and game["status"] == GameStatus.IN_PROGRESS:
        ai_pos = ai_move(board)
        board[ai_pos] = "O"
        game["moves"] += 1
        winner = check_winner(board)
        if winner:
            game["status"] = GameStatus.FINISHED
            game["winner"] = winner
            update_scores(winner)
        elif is_full(board):
            game["status"] = GameStatus.TIE
        else:
            game["next_player"] = "X"

    return GameStateResponse(**game)

# PUBLIC_INTERFACE
@app.get("/state/{game_id}", tags=["game"], summary="Get the current state of a game", response_model=GameStateResponse)
def get_game_state(game_id: str):
    """
    Get the full state of the specified game.
    - Returns board, whose turn, game status, winner (if any), scores, etc.
    """
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    return GameStateResponse(**games[game_id])

# PUBLIC_INTERFACE
@app.get("/scores", tags=["game"], summary="Get current overall scores")
def get_scores():
    """
    Get the score statistics for all games played in this server session.
    """
    return dict(global_scores)
