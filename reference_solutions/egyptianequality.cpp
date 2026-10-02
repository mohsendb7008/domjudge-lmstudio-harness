#include<iostream>
#include<vector>
using namespace std;
typedef vector<int> vi;

void bail() {
    cout << "impossible\n";
    exit(0);
}

int dx[4] = { 0, 1, 0, -1 };
int dy[4] = { 1, 0, -1, 0 };

struct unionfind {
  vi p;
  int c;
  unionfind(int n) : p(n, -1), c(n) { }
  int find(int x) {
    return p[x] < 0 ? x : p[x] = find(p[x]);
  }
  bool united(int x, int y) {
    return find(x) == find(y);
  }
  void unite(int x, int y) {
    int a = find(x), b = find(y);
    if(a == b) return;
    if(p[a] > p[b]) swap(a, b);
    p[a] += p[b];
    p[b] = a;
    c--;
    return;
  }
  int size(int x) {
    return -p[find(x)];
  }
};

bool test_solution(vector<string> &poss, vector<string> &orig) {
    int h = poss.size(), w = poss[0].size();
    unionfind uf(h * w);
    int sing = 0, ac = 0, bc = 0;
    for(int i = 0; i < h; ++i) {
        for(int j = 0; j < w; ++j) {
            if(orig[i][j] == '#') {
                if(poss[i][j] != '#')
                    return false;
                sing++;
                continue;
            }
            if(poss[i][j] != 'A' &&
                poss[i][j] != 'B')
                return false;
            if(orig[i][j] == 'C') {
                if(poss[i][j] == 'A') ac++;
                else bc++;
            }
            int ind = i * w + j;
            for(int k = 0; k < 4; ++k) {
                int i2 = i + dx[k];
                int j2 = j + dy[k];
                int ind2 = i2 * w + j2;
                if(i2 < 0 || i2 >= h) continue;
                if(j2 < 0 || j2 >= w) continue;
                if(poss[i2][j2] != poss[i][j])
                    continue;
                uf.unite(ind, ind2);
            }
        }
    }
    return uf.c == sing + 2 && ac == bc;
}

void print_solution(vector<string> &sol) {
    for(string s : sol)
        cout << s << '\n';
    exit(0);
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    int n; cin >> n;
    vector<string> inp(n);
    for(string &s : inp) cin >> s;
    int cnum = 0;
    for(string s : inp)
        for(char c : s)
            if(c == 'C') cnum++;
    if(cnum % 2) bail();
    vector<string> base = inp;
    for(string &s : base)
        for(char &c : s)
            if(c != '#')
                c = 'A';
    vector<string> cur = base;
    int left = cnum / 2;
    for(int col = 0; col < 2 * n - 1; ++col) {
        bool up = col < n;
        for(int row = up ? n - 1 : 0; up ? row >= 0 : row < n; up ? --row : ++row) {
            if(inp[row][col] == '#') continue;
            cur[row][col] = 'B';
            if(inp[row][col] == 'C') left--;
            if(left == 0) break;
        }
        if(left == 0) break;
    }
    if(test_solution(cur, inp))
        print_solution(cur);
    cur = base;
    left = cnum / 2;
    for(int col = 2 * n - 2; col >= 0; --col) {
        bool up = col >= n - 1;
        for(int row = up ? n - 1 : 0; up ? row >= 0 : row < n; up ? --row : ++row) {
            if(inp[row][col] == '#') continue;
            cur[row][col] = 'B';
            if(inp[row][col] == 'C') left--;
            if(left == 0) break;
        }
        if(left == 0) break;
    }
    if(test_solution(cur, inp))
        print_solution(cur);
    cur = base;
    left = cnum / 2;
    for(int row = 0; row < n; ++row) {
        for(int it = 0; it < 2 * row + 1; ++it) {
            int ind = it;
            if(row != 0) {
                if(ind == 0) ind = 1;
                else if(ind == 1) ind = 0;
            }
            int col = n - 1 - row + ind;
            if(inp[row][col] == '#') continue;
            cur[row][col] = 'B';
            if(inp[row][col] == 'C') left--;
            if(left == 0) break;
        }
        if(left == 0) break;
    }
    if(test_solution(cur, inp))
        print_solution(cur);
    cur = base;
    left = cnum / 2;
    for(int ind = 0; ind < 2 * n - 1; ++ind) {
        for(int row = 0; row < n; ++row) {
            int col = n - 1 - row + ind;
            if(col < 0 || col >= 2 * n - 1) continue;
            if(inp[row][col] == '#') continue;
            cur[row][col] = 'B';
            if(inp[row][col] == 'C') left--;
            if(left == 0) break;
        }
        if(left == 0) break;
    }
    if(test_solution(cur, inp))
        print_solution(cur);
    cur = base;
    left = cnum / 2;
    for(int ind = 0; ind < 2 * n - 1; ++ind) {
        for(int row = 0; row < n; ++row) {
            int col = n - 1 + row - ind;
            if(col < 0 || col >= 2 * n - 1) continue;
            if(inp[row][col] == '#') continue;
            cur[row][col] = 'B';
            if(inp[row][col] == 'C') left--;
            if(left == 0) break;
        }
        if(left == 0) break;
    }
    if(test_solution(cur, inp))
        print_solution(cur);
    bail();
}
