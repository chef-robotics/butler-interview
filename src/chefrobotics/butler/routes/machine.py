import subprocess
import traceback

from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel

machine_router = APIRouter(prefix="/machine", tags=["machine"])
KEYPRESS_WINDOW = "KEYPRESS_WINDOW"


# This follows the schema of chef_common_msgs/StringStamped
class MachineCommandRequest(BaseModel):
    header: str
    data: str


@machine_router.post("/command")
async def handle_window_command(request: MachineCommandRequest):
    if request.data == KEYPRESS_WINDOW:
        print("Received keypress window")
        try:
            # TODO(kyle): make a gnome shell extension that does this, instead
            subprocess.run(["xdotool", "key", "Super_L"], check=True)
            return {"success": True, "message": "Window switch triggered"}
        except subprocess.CalledProcessError as e:
            print("xdotool execution failed:", e)
            traceback.print_exc()
            raise HTTPException(
                status_code=500, detail="Failed to execute window switch"
            )

    raise HTTPException(
        status_code=422, detail=f"Unsupported command: {request.data}"
    )
