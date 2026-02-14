"""Restricted Python execution sandbox for DCSS AI."""
import ast
import builtins
import signal
import io
from typing import Dict, Any

from .game import DCSSGame, Direction


ALLOWED_BUILTINS = {
    'len', 'range', 'min', 'max', 'sorted', 'list', 'dict', 'set', 'tuple',
    'str', 'int', 'float', 'bool', 'enumerate', 'zip', 'any', 'all',
    'abs', 'round', 'isinstance', 'type', 'hasattr', 'getattr',
    'True', 'False', 'None', 'reversed', 'map', 'filter', 'sum',
}

FORBIDDEN_CALLS = {
    'exec', 'eval', 'compile', 'open', '__import__', 'input',
    'breakpoint', 'exit', 'quit',
}

FORBIDDEN_ATTRS = {
    '__class__', '__bases__', '__subclasses__', '__dict__', '__globals__',
    '__code__', '__closure__', '__func__', '__self__', '__module__',
    '__mro__', '__builtins__',
}


class Sandbox:
    """Restricted Python execution environment for DCSS game code."""
    
    def __init__(self, game: DCSSGame):
        self.game = game
    
    def execute(self, code: str, timeout: int = 10) -> Dict[str, Any]:
        """Execute code in sandbox. Returns {output, error, messages}."""
        # AST validation
        try:
            tree = ast.parse(code)
            _validate_ast(tree)
        except SyntaxError as e:
            return {"output": "", "error": f"Syntax error: {e}", "messages": []}
        except ValueError as e:
            return {"output": "", "error": str(e), "messages": []}
        
        msg_start = len(self.game._messages)
        output_buf = io.StringIO()
        
        def safe_print(*args, **kwargs):
            kwargs.pop('file', None)  # ignore file= arg
            text = " ".join(str(a) for a in args)
            end = kwargs.get('end', '\n')
            output_buf.write(text + end)
            # Limit output size
            if output_buf.tell() > 10000:
                raise RuntimeError("Output too large (>10KB)")
        
        # Build restricted builtins dict
        safe_builtins = {}
        for name in ALLOWED_BUILTINS:
            val = getattr(builtins, name, None)
            if val is not None:
                safe_builtins[name] = val
        safe_builtins['print'] = safe_print
        
        restricted_globals = {
            '__builtins__': safe_builtins,
            'dcss': self.game,
            'Direction': Direction,
        }
        
        result = {"output": "", "error": "", "messages": []}
        
        # Set timeout
        old_handler = signal.getsignal(signal.SIGALRM)
        
        def _timeout(signum, frame):
            raise TimeoutError("Code execution timed out")
        
        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(timeout)
        
        try:
            exec(compile(tree, "<sandbox>", "exec"), restricted_globals)
            result["output"] = output_buf.getvalue()
        except TimeoutError:
            result["error"] = "Execution timed out (10s limit)"
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            result["output"] = output_buf.getvalue()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        
        # Collect new game messages
        new_msgs = self.game._messages[msg_start:]
        if new_msgs:
            result["messages"] = list(new_msgs)
        
        return result


def _validate_ast(tree: ast.AST):
    """Validate AST — reject imports, forbidden calls, dangerous attrs."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("Imports are not allowed")
        
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                raise ValueError(f"'{node.func.id}' is not allowed")
        
        if isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRS:
                raise ValueError(f"Access to '{node.attr}' is not allowed")
